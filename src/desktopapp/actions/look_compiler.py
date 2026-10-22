"""Standalone offline look compilation adapter used by any frontend."""
from pathlib import Path

def run(args):
    from looktool.compilelook import main
    argv = [args['source'], '--name', args['name'], '--output', args['output'],
            '--calibration', args['model'], '--passes', str(args.get('passes', 3)),
            '--extra-colors',str(args.get('extra_colors',256))]
    if args.get('evaluations') is not None:
        argv += ['--evaluations', str(args['evaluations'])]
    if Path(args['source']).suffix.lower() == '.cube':
        argv += ['--input-space', args.get('input_space', 'sony-st-srgb')]
        if args.get('bridge'):
            argv += ['--bridge', args['bridge']]

    code = main(argv)
    if code:
        raise RuntimeError('A7Look conversion did not complete')
    return {'output': args['output'], 'exit_code': code}
