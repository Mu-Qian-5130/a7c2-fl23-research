"""Feature dependencies and byte ownership are checked before image editing."""
import pytest
from desktopapp import firmwarefeatures,firmwarelocal


@pytest.mark.parametrize('args',[
    dict(voice_cleanup=False),dict(ssh=True,custom_looks=False),
    dict(preset_pack='pack',custom_looks=False),dict(looks=[{}],custom_looks=False),dict(precapture=True),
    dict(precapture=True,vertical=True,ssh=True,custom_looks=True)])
def test_unsupported_dependency_never_creates_a_candidate(tmp_path,args):
    out=tmp_path/'build'
    with pytest.raises(ValueError):firmwarelocal.build(dict(sony_firmware='unused',workspace=str(out),**args),tmp_path)
    assert not out.exists()


@pytest.mark.parametrize('vertical',[False,True])
@pytest.mark.parametrize('sound',[False,True])
@pytest.mark.parametrize('custom',[False,True])
def test_independent_selections_and_mandatory_voice_cleanup(vertical,sound,custom):
    result=firmwarefeatures.options(dict(vertical=vertical,sound=sound,custom_looks=custom,ssh=custom))
    assert result['vertical']==vertical and result['sound']==sound and result['custom_looks']==custom
    assert result['voice_cleanup'] and not result['precapture']


def test_overlapping_features_fail_without_partly_applying_the_second():
    plan=firmwarefeatures.Composition({'cpapp-b.bin':bytes(40)})
    plan.apply('look',{'cpapp-b.bin':b'\1'+bytes(39)})
    # A nearby unchanged byte is not owned merely because difference spans coalesce it.
    plan.apply('sound',{'cpapp-b.bin':b'\1\2'+bytes(38)})
    before=dict(plan.current)
    with pytest.raises(ValueError,match='look'):
        plan.apply('other',{'cpapp-b.bin':b'\3\2\4'+bytes(37)})
    assert plan.current==before and len(plan.rows)==2
