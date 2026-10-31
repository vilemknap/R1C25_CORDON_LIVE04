"""Differential parser tests: independent original collector vs streaming proof."""
import copy
import hashlib
import random
from pathlib import Path
import pytest
from cordon2025.common import parent_module
from cordon2025.visum_startup import ReadControl,_geometry_equal
from cordon2025.diagfast_geometry import ReferenceGeometry

EDGES=[(1,10,20),(2,20,10),(3,10,30),(4,30,10),(5,10,20)]
LINKS={k:{'eligible':False,'tsys':('C',)} for k in EDGES}

def routes(n=5):
    return [((i+1,i+2,1), [EDGES[0],EDGES[1]]*(1+i%3) if i%4 else []) for i in range(n)] + [((900,900,1),[])]

def rows(groups, form='hierarchical'):
    result=[]
    for key,path in groups:
        if form!='flat' or not path:result.append([*key,'','','',''])
        for idx,edge in enumerate(path,1):
            parent=key if form=='flat' else ('','','')
            if form=='partial':parent=(key[0],'',key[2])
            result.append([*parent,idx,*edge])
    return result

def collector(path,groups,**settings):
    two=parent_module('r1_15a2_two_mode_v238');sup=parent_module('r1_15a2_supply')
    ctl=ReadControl(path.parent)
    c=two.TwoModeRouteCollector([],sup.SupplyPolicy(),'test',LINKS,path,
          dict(min_free_disk_gib=0,commit_routes=2,**settings),ctl,geometry_only=True)
    pr=[(*key,0. if i%2 else 1.) for i,(key,p) in enumerate(groups)]
    total=sum(v for o,d,ix,v in pr if o!=d)
    c.add_parents('NATIVE_CW','C',pr,{'matrix_interzonal':total})
    return c

def trial(tmp_path, stream, groups=None, **settings):
    groups=groups or routes();main=collector(tmp_path/'ref.sqlite',groups)
    other=collector(tmp_path/'old.sqlite',groups,**settings)
    try:
        main.add_geometry('C',rows(groups))
        main.settings.update(settings)
        ref=ReferenceGeometry(main,'C')
        results=[]
        for f in (lambda:(other.add_geometry('C',iter(stream)),_geometry_equal(main.db,other.db,'C')),
                  lambda:ref.verify(iter(stream),'NATIVE_CW')):
            try:results.append(('PASS',f()))
            except Exception as e:results.append(('FAIL',str(e).split(':')[0]))
        ref.close();return results
    finally:other.close();main.close()

@pytest.mark.parametrize('form',['hierarchical','flat','partial'])
@pytest.mark.parametrize('reverse',[False,True])
def test_legal_variants_and_reordered_groups(tmp_path,form,reverse):
    g=routes(307);stream=rows(g[::-1] if reverse else g,form)
    result=trial(tmp_path,stream,g)
    assert [x[0] for x in result]==['PASS','PASS']
    proof=result[1][1]
    assert proof['geometry_routes']==len(g) and proof['packed_bytes_compared']
    assert not proof['scratch_sqlite_created']
    assert proof['zero_link_intrazonal_paths']==1

@pytest.mark.parametrize('damage',['missing_route','extra_route','duplicate_parent','orphan_child','partial_conflict',
 'bad_width','partial_child','incomplete_parent','gap','disconnected','unknown_edge','same_no_wrong_end',
 'swap_paths','parallel_different','reordered_children','bad_id','negative_index','nan_id','reopened_flat'])
def test_negative_semantics_match_oracle(tmp_path,damage):
    g=routes();x=rows(g)
    if damage=='missing_route':x=x[:-1]
    elif damage=='extra_route':x.append([999,998,1,'','','',''])
    elif damage=='duplicate_parent':x=x[:1]+x
    elif damage=='orphan_child':x=[['','','',1,*EDGES[0]]]+x
    elif damage=='partial_conflict':x[2][0]=123
    elif damage=='bad_width':x[2]=x[2][:-1]
    elif damage=='partial_child':x[2][4]=''
    elif damage=='incomplete_parent':x[0][1]=''
    elif damage=='gap':x[2][3]=4
    elif damage=='disconnected':x[3][4:]=EDGES[0]
    elif damage=='unknown_edge':x[2][4]=999
    elif damage=='same_no_wrong_end':x[2][6]=31
    elif damage=='swap_paths':x[0][2]=2
    elif damage=='parallel_different':x[2][4:]=EDGES[4]
    elif damage=='reordered_children':x[2],x[3]=x[3],x[2]
    elif damage=='bad_id':x[0][0]='x'
    elif damage=='negative_index':x[2][3]=-1
    elif damage=='nan_id':x[0][0]=float('nan')
    elif damage=='reopened_flat':x+=rows([g[1]],'flat')
    old,new=trial(tmp_path,x,g)
    assert old[0]==new[0]=='FAIL'
    assert old[1]==new[1]

@pytest.mark.parametrize('limit',[1,2,3])
def test_route_length_budget_unchanged(tmp_path,limit):
    g=[((1,2,1),[EDGES[0],EDGES[1]]*3)]
    old,new=trial(tmp_path,rows(g),g,max_links_per_path=limit)
    assert old==new==('FAIL','SINGLE_ROUTE_LENGTH_BUDGET_EXCEEDED')

def test_raw_rows_limit(tmp_path):
    g=routes();old,new=trial(tmp_path,rows(g),g,max_geometry_rows_per_mode=1)
    assert old==new==('FAIL','GEOMETRY_ROW_BUDGET_EXCEEDED')

def test_zero_flow_and_positive_zero_link_both_kept(tmp_path):
    g=[((1,2,1),[]),((2,3,1),[]),((3,3,1),[])]
    old,new=trial(tmp_path,rows(g),g)
    assert old[0]==new[0]=='PASS'
    assert new[1]['zero_link_interzonal_paths']==2

def test_corrupt_representative_blob_detected(tmp_path):
    g=routes();c=collector(tmp_path/'ref.sqlite',g)
    try:
        c.add_geometry('C',rows(g));r=ReferenceGeometry(c,'C')
        c.db.execute("UPDATE geometry SET edge_ids=x'00000000' WHERE orig=2")
        with pytest.raises(Exception,match='BLOB_DIFFERS'):r.verify(rows(g),'NATIVE_CW')
        r.close()
    finally:c.close()
