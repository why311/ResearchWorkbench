"""Replay one exported repository run inside the same restricted Docker setup."""
import argparse
import json
from pathlib import Path
import subprocess
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    repo, output = Path(args.repository).resolve(), Path(args.output).resolve()
    if output.is_relative_to(repo) or repo.is_relative_to(output):
        raise ValueError('Output and repository directories must not overlap')
    entry = (repo / config['entry']).resolve()
    if not entry.is_relative_to(repo) or not entry.is_file() or entry.suffix != '.py':
        raise ValueError('Entry must be a Python file inside the exported repository')
    output.mkdir(parents=True, exist_ok=True)
    name = 'research-replay-' + uuid.uuid4().hex
    command = ['docker', 'run', '--rm', '--name', name, '--network', 'none', '--cpus', '2', '--memory', '2g', '--pids-limit', '128', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--read-only', '--tmpfs', '/tmp:rw,size=128m', '--mount', f'type=bind,source={repo},target=/workspace,readonly', '--mount', f'type=bind,source={output},target=/output', '-w', '/workspace', '-e', 'RESEARCH_OUTPUT=/output', '-e', 'PYTHONDONTWRITEBYTECODE=1', '-e', 'MPLCONFIGDIR=/tmp/matplotlib', 'research-workbench:0.1', 'python', '-u', config['entry'], *config['args']]
    try:
        subprocess.run(command, check=True, timeout=config['timeout'])
    finally:
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=15)


if __name__ == '__main__':
    main()
