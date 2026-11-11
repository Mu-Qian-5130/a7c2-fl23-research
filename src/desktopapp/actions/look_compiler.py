"""Standalone offline look compilation adapter used by any frontend."""
from pathlib import Path

def run(args):
    from looktool.compilelook import main
    argv = [args['source'], '--name', args['name'], '--output', args['output'],
            '--calibration', args['model'], '--passes', str(args.get('passes', 12))]
    if args.get('evaluations') is not None:
        argv += ['--evaluations', str(args['evaluations'])]
    if args.get('dcp_output'):
        argv += ['--dcp-output',args['dcp_output']]
    if args.get('include_menu_icon',True) is False:
        argv += ['--without-menu-icon']
    elif args.get('menu_icon_text'):
        argv += ['--menu-icon-text',args['menu_icon_text']]
    if Path(args['source']).suffix.lower() == '.cube':
        argv += ['--input-space', args.get('input_space', 'sony-st-srgb')]
        if args.get('bridge'):
            argv += ['--bridge', args['bridge']]

    code = main(argv)
    if code:
        raise RuntimeError('A7Look conversion did not complete')
    companion=Path(args['dcp_output'])if args.get('dcp_output')else Path(args['output']).with_suffix('.dcp')
    return {'output': args['output'], 'dcp_output':str(companion), 'exit_code': code}
