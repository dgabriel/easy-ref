"""CLI skeleton; live harnesses are intentionally unavailable at this gate."""
import argparse


def main():
    parser = argparse.ArgumentParser(prog='easy-ref')
    sub = parser.add_subparsers(dest='command', required=True)
    run = sub.add_parser('run')
    run.add_argument('order')
    run.add_argument('--repo', default='.')
    run.add_argument('--builder', default='codex')
    run.add_argument('--reviewer', default='claude')
    for name in ('status', 'answer', 'stop'):
        command = sub.add_parser(name)
        command.add_argument('run_id', nargs='?' if name == 'status' else None)
        if name == 'answer':
            command.add_argument('decision')
    parser.parse_args()
    parser.error('CLI execution is unavailable until harness and command integration')


if __name__ == '__main__':
    main()
