"""Portable full-library catalogs reject invalid paths and unaccepted mono."""
import pytest
import profilepack

def catalog():
    return dict(schema='a7c2-profile-library/2',count=1,profiles=[dict(name='Kodak 2383',dcp='Kodak/Kodak 2383.dcp',a7look='Kodak/Kodak 2383.a7look')])

def test_full_library_accepts_matched_arbitrary_style():
    assert profilepack.paired_paths(catalog())=={('Kodak/Kodak 2383.dcp','Kodak/Kodak 2383.a7look')}

@pytest.mark.parametrize('value',[None,13,[],{},'../escape.dcp','/absolute.dcp','C:/absolute.dcp','a\\b.dcp'])
def test_full_library_rejects_nonportable_paths(value):
    c=catalog();c['profiles'][0]['dcp']=value
    with pytest.raises(ValueError):profilepack.paired_paths(c)

def test_full_library_requires_matching_pairs_unique_names_and_mono_acceptance():
    c=catalog();c['profiles'][0]['a7look']='Other.a7look'
    with pytest.raises(ValueError):profilepack.paired_paths(c)
    c=catalog();c['profiles']*=2;c['count']=2
    with pytest.raises(ValueError):profilepack.paired_paths(c)
    c=catalog();c['profiles'][0]['monochrome']=True
    with pytest.raises(ValueError):profilepack.paired_paths(c)
    c['profiles'][0]['independent_prediction']=dict(RGB_MAE_8bit=3,RGB_P95_8bit=12)
    assert len(profilepack.paired_paths(c))==1
