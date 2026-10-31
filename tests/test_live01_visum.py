import pytest
from cordon2025.live01_config import load_config
from cordon2025.live01_visum import model_preflight,read_donor_state,ReadOnlyObject
from cordon2025.visum_startup import ReadControl,settings
from fake_live01 import Live01Visum
from fake_visum_startup import BusyError

@pytest.fixture
def case(tmp_path):
    v=Live01Visum(tmp_path/'model');folder=tmp_path/'out';folder.mkdir()
    return v,load_config(),folder,ReadControl(folder),settings({'min_free_disk_gib':0,'com_retry_initial_delay_seconds':0.,'com_retry_max_delay_seconds':0.,'com_retry_attempts':3})

def test_native_contract_over_realistic_fake(case):
    pre,state=model_preflight(*case)
    assert len(pre[2])==681 and pre[2][0]==5
    assert len(state['zone_rows'])==681 and len(state['actuatable_zones'])==650
    assert len(state['td_rows'])==16 and len(state['foreign_td_parameters'])==3
    assert len(state['od_segment_bindings'])==12 and len(state['assignment']['required_full_scope'])==14
    assert len(state['script_references'])==1 and not case[0].writes

@pytest.mark.parametrize('attr',['ADD_PROD_W','ADD_ATT_W','ADD_PROD_S','ADD_ATT_S','ADD_SALARY','ZAHR_PROD_WORK','ZAHR_ATR_WORK','ZAHR_PROD_SERV','ZAHR_ATR_SERV','POP_ZP','NOT_ZAHR','AV_INCOME'])
def test_missing_required_zone_data_blocks(case,attr):
    del case[0].Net.Zones.rows[0][attr]
    with pytest.raises(Exception,match='TG_CONTRACT_MISSING'):model_preflight(*case)
    assert not case[0].writes

@pytest.mark.parametrize('value',[None,float('nan'),float('inf')])
def test_nonfinite_zone_data_blocks(case,value):
    case[0].Net.Zones.rows[0]['ADD_PROD_W']=value
    with pytest.raises(Exception,match='TG_CONTRACT_MISSING'):model_preflight(*case)

@pytest.mark.parametrize('damage,code',[('matrix','OD_MATRIX_BINDING'),('op','TG_CONTRACT_MISSING'),('scope','ASSIGNMENT_SCOPE'),('script','PROCEDURE_SCRIPT_MISSING'),('motorway','MOTORWAY_MODE'),('axis','DUPLICATE'),('type','TG_CONTRACT_MISSING'),('td','TD_SOURCE_SET')])
def test_wrong_model_contracts(case,damage,code):
    v=case[0]
    if damage=='matrix':v.dsegs['NATIVE_CW'].ODMatrix.no=10
    elif damage=='op':v.Procedures.Operations.items[4].values['OPERATIONTYPE']=46
    elif damage=='scope':v.Procedures.Operations.items[19].PrTAssignmentParameters.values['DSEGSET']='LNV,NV'
    elif damage=='script':v.source.parent.joinpath('20B_synthetic.py').unlink()
    elif damage=='motorway':v.Net.Links.rows[0]['TSYSSET']='C,C_noT'
    elif damage=='axis':v.Net.Zones.rows[1]['NO']=v.Net.Zones.rows[0]['NO']
    elif damage=='type':v.Net.Zones.Attributes.items[0].ValueType=5
    elif damage=='td':v.Procedures.Operations.items[5].TripDistributionParameters.values['DSTRATSET']+=',BAD'
    with pytest.raises(Exception,match=code):model_preflight(*case)
    assert not v.writes

@pytest.mark.parametrize('name',['SetAttValue','SetValues','SetMultiAttValues','Execute','SaveVersion','LoadVersion','CreateSomething'])
def test_read_facade_denies_mutators(case,name):
    v,c,f,ctl,opt=case;p=ReadOnlyObject(v,ctl,opt)
    with pytest.raises(ValueError,match='WRITE_FORBIDDEN'):getattr(p,name)
    assert not v.writes


def test_read_retry_single_owner(case):
    v,c,f,ctl,opt=case;v.failures['AttValue:PARA_A']=(2,BusyError)
    _,state=model_preflight(*case)
    assert state and len(ctl.com_retry_events)==2 and not v.writes


def test_scope_respects_exclusions(case):
    case[1]['explicit_excluded_zone_nos']=[5,6005]
    _,state=model_preflight(*case)
    assert len(state['actuatable_zones'])==648
    assert 5 not in state['actuatable_zones']
