"""Native output fixture for frontend wiring, separate from numerical fitting."""
import copy
import json
from looktool import r5fit

def result():
    template=json.loads((r5fit.ROOT/'data/template.json').read_text(encoding='utf-8'))
    return copy.deepcopy(template['fitted']),bytes(1215),dict(metrics={},fixture_only=True,physical_color_accuracy_verified=False)
