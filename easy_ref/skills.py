"""Bounded, owner-supplied role skills, snapshotted outside the worktree."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat

ROLES = ('builder', 'reviewer')
LIMIT = 128 * 1024
PRECEDENCE = ("easy-ref's rules, the work order, and the required output format take precedence "
              "over these skills. For reviewers, return the verdict JSON, not the skill's own report format.")


def valid_name(name):
    return isinstance(name, str) and name not in ('', '.', '..') and '/' not in name and '\0' not in name


def no_links(path):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('skill paths must not contain symlinks')


def read_file(path, remaining):
    no_links(path)
    # O_NONBLOCK prevents a substituted FIFO from blocking; O_NOFOLLOW rejects links.
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError('skill files must be regular files')
        data = handle.read(remaining + 1)
    if len(data) > remaining:
        raise ValueError('skill text exceeds 128 KB per role')
    data.decode('utf-8')
    return data


def validate_name(data, name):
    lines = data.decode('utf-8').splitlines()
    if not lines or lines[0] != '---' or '---' not in lines[1:]:
        raise ValueError('SKILL.md requires frontmatter with a matching name')
    header = lines[1:lines.index('---', 1)]
    names = [line[5:].strip() for line in header if line.startswith('name:')]
    # Support plain and quoted scalar names without a YAML dependency. Other
    # frontmatter (e.g. multiline descriptions) is preserved verbatim.
    if len(names) != 1:
        raise ValueError('SKILL.md requires exactly one frontmatter name')
    value = names[0]
    if value.startswith('"'):
        try:
            value = json.loads(value)
        except ValueError:
            raise ValueError('invalid skill name scalar') from None
    elif value.startswith("'") and value.endswith("'"):
        value = value[1:-1].replace("''", "'")
    else:
        value = re.split(r'\s+#', value, maxsplit=1)[0]
    if value != name:
        raise ValueError('frontmatter name must match skill directory name')


def digest(files):
    """Hash a canonical filename-to-file-digest manifest, including file names."""
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def collect(repo, config):
    result = {}
    for role in ROLES:
        skills = {}
        total = 0
        for source in config[role + '_skills']:
            path = Path(repo) / source
            no_links(path)
            if not path.is_dir():
                raise ValueError('skill path must be a directory')
            name = path.name
            if not valid_name(name):
                raise ValueError('invalid skill directory name')
            if name in skills:
                raise ValueError('duplicate skill name within role: ' + name)
            paths = [path / 'SKILL.md']
            references = path / 'references'
            no_links(references)
            if references.exists():
                if not references.is_dir():
                    raise ValueError('skill references must be a directory')
                paths += sorted(references.glob('*.md'))
            files = {}
            for file in paths:
                data = read_file(file, LIMIT - total)
                total += len(data)
                files[file.relative_to(path).as_posix()] = data
            validate_name(files['SKILL.md'], name)
            skills[name] = files
        result[role] = skills
    return result


def freeze(directory, collected):
    records = {}
    for role, skills in collected.items():
        records[role] = []
        for name, files in skills.items():
            for relative, data in files.items():
                path = Path(directory) / 'skills' / role / name / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            records[role].append({'name': name, 'sha256': digest(files), 'files': list(files)})
    return records


def section(state, role):
    records = state.get('skills', {}).get(role, [])
    if not records:
        if state['config'].get(role + '_skills'):
            raise ValueError('frozen skill records missing')
        return ''
    parts = ['\n\n## Owner-supplied skills\n', PRECEDENCE + '\n']
    total = 0
    names = set()
    for record in records:
        name = record['name']
        if not valid_name(name) or name in names:
            raise ValueError('invalid frozen skill name')
        names.add(name)
        files = {}
        for relative in record['files']:
            if relative != 'SKILL.md' and not re.fullmatch(r'references/[^/]+\.md', relative):
                raise ValueError('invalid frozen skill file')
            data = read_file(Path(state['run_dir']) / 'skills' / role / name / relative, LIMIT - total)
            total += len(data)
            files[relative] = data
        if 'SKILL.md' not in files or digest(files) != record['sha256']:
            raise ValueError('frozen skill digest mismatch')
        for relative, data in files.items():
            parts.append(f'\n### {name}/{relative}\n\n' + data.decode('utf-8') + '\n')
    return ''.join(parts)
