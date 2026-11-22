#!/usr/bin/env python3
"""Build payload/apps/nzstore.ipk from the nzstore/ sources.

Usage:  python3 tools/build-ipk.py [SRC_DIR] [OUT_IPK]
        (defaults: nzstore/  payload/apps/nzstore.ipk, relative to the repo root)

Produces the same layout as the original package (ar archive with
debian-binary, control.tar.gz, data.tar.gz; app under
usr/palm/applications/<id>/ plus usr/palm/packages/<id>/packageinfo.json), with:
  - LF line endings in text files, even from a Windows checkout
  - dirs 755 / files 644 (the original shipped 777 dirs)
  - config.js ALWAYS generated from config.js.example (placeholder token),
    so a local config.js holding a real token can never be packaged
  - reproducible output: set SOURCE_DATE_EPOCH to pin timestamps
"""
import gzip, io, json, os, sys, tarfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(ROOT, 'nzstore')
OUT = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else os.path.join(ROOT, 'payload', 'apps', 'nzstore.ipk')
MTIME = int(os.environ.get('SOURCE_DATE_EPOCH', time.time()))
OWNER = 1001  # same uid/gid as the original package
TEXT_EXT = ('.js', '.html', '.css', '.json', '.example', '.txt')
SKIP = {'config.js'}  # generated below from config.js.example


def read_src(name):
    with open(os.path.join(SRC, name), 'rb') as f:
        data = f.read()
    if name.endswith(TEXT_EXT):
        data = data.replace(b'\r\n', b'\n')
    return data


def tar_gz(entries):
    """entries: list of (path, bytes or None for a directory)."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode='w', format=tarfile.PAX_FORMAT) as t:
        for path, data in entries:
            ti = tarfile.TarInfo(path)
            ti.mtime, ti.uid, ti.gid = MTIME, OWNER, OWNER
            if data is None:
                ti.type, ti.mode = tarfile.DIRTYPE, 0o755
                t.addfile(ti)
            else:
                ti.mode, ti.size = 0o644, len(data)
                t.addfile(ti, io.BytesIO(data))
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode='wb', mtime=MTIME) as g:
        g.write(raw.getvalue())
    return out.getvalue()


def ar_member(name, data):
    hdr = '%-16s%-12d%-6d%-6d%-8s%-10d`\n' % (name, MTIME, 0, 0, '100644', len(data))
    assert len(hdr) == 60
    return hdr.encode() + data + (b'\n' if len(data) % 2 else b'')


def main():
    info = json.loads(read_src('appinfo.json'))
    app_id, version = info['id'], info['version']

    if not os.path.isfile(os.path.join(SRC, 'config.js.example')):
        sys.exit('config.js.example missing in ' + SRC)
    config = read_src('config.js.example')
    if b"NZ_TOKEN = 'CHANGE-ME" not in config:
        sys.exit("config.js.example must hold the placeholder NZ_TOKEN = 'CHANGE-ME...' "
                 "(the installer replaces it with the real token)")

    files = sorted(n for n in os.listdir(SRC)
                   if os.path.isfile(os.path.join(SRC, n)) and n not in SKIP and not n.startswith('.'))
    app_dir = 'usr/palm/applications/' + app_id
    pkg_dir = 'usr/palm/packages/' + app_id
    pkginfo = json.dumps({'id': app_id, 'version': version, 'app': app_id}, separators=(',', ':')).encode()

    entries = [(d, None) for d in ('usr', 'usr/palm', 'usr/palm/applications', app_dir,
                                   'usr/palm/packages', pkg_dir)]
    entries += [(app_dir + '/' + n, read_src(n)) for n in files]
    entries.append((app_dir + '/config.js', config))
    entries.append((pkg_dir + '/packageinfo.json', pkginfo))

    size_kb = max(1, (sum(len(d) for _, d in entries if d) + 1023) // 1024)
    control = ('Package: %s\nVersion: %s\nSection: misc\nPriority: optional\nArchitecture: all\n'
               'Installed-Size: %d\nMaintainer: NatxoBSD <nobody@example.com>\n'
               'Description: built by build-ipk.py\nwebOS-Package-Format-Version: 2\n'
               'webOS-Packager-Version: x.y.x\n') % (app_id, version, size_kb)

    ipk = (b'!<arch>\n' + ar_member('debian-binary', b'2.0\n')
           + ar_member('control.tar.gz', tar_gz([('control', control.encode())]))
           + ar_member('data.tar.gz', tar_gz(entries)))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'wb') as f:
        f.write(ipk)
    print('built %s (%s %s, %d files, %d bytes)' % (OUT, app_id, version, len(files) + 2, len(ipk)))


if __name__ == '__main__':
    main()
