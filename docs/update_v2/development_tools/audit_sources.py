from pathlib import Path
import hashlib,json,difflib,ast
R=Path('/mnt/data/R1_CORDON_UPDATE_20261022'); O=R/'audit'; O.mkdir(exist_ok=True)
roots={'base':R/'baseline/parent_v24915','v1':R/'baseline/cordon_v1/R1_2025_CORDON_OPTIMIZER_V1_OFFLINE_20261019/parent','resume':R/'upstream/donor_resume','fresh':R/'upstream/donor_fresh'}
def inventory(p):
 return {str(f.relative_to(p)):{'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'bytes':f.stat().st_size} for f in sorted(p.rglob('*')) if f.is_file() and '__pycache__' not in f.parts}
invs={k:inventory(p) for k,p in roots.items()}
(O/'SOURCE_INVENTORIES.json').write_text(json.dumps(invs,indent=2))
comparisons={}
for a,b in [('base','v1'),('base','resume'),('base','fresh'),('resume','fresh')]:
 ia,ib=invs[a],invs[b]; changed=sorted(k for k in set(ia)&set(ib) if ia[k]['sha256']!=ib[k]['sha256']); added=sorted(set(ib)-set(ia)); removed=sorted(set(ia)-set(ib))
 comparisons[a+'__'+b]={'changed':changed,'added':added,'removed':removed}
 print('\n',a,b,'changed',len(changed),'added',len(added),'removed',len(removed)); print('CHANGED_PY',*[k for k in changed if k.endswith('.py')],sep='\n')
 dest=O/('diff_'+a+'__'+b); dest.mkdir(exist_ok=True)
 for k in changed:
  if k.endswith(('.py','.json','.md','.txt')) and ia[k]['bytes']<1500000 and ib[k]['bytes']<1500000:
   sa=(roots[a]/k).read_text(encoding='utf-8-sig',errors='replace').splitlines(True); sb=(roots[b]/k).read_text(encoding='utf-8-sig',errors='replace').splitlines(True)
   patch=''.join(difflib.unified_diff(sa,sb,fromfile=a+'/'+k,tofile=b+'/'+k))
   p=dest/(k+'.diff');p.parent.mkdir(parents=True,exist_ok=True);p.write_text(patch)
(O/'COMPARISON.json').write_text(json.dumps(comparisons,indent=2))
# public function/class changes in root modules
rows=[]
for tag in ('resume','fresh'):
 for rel in comparisons['base__'+tag]['changed']+comparisons['base__'+tag]['added']:
  if not rel.endswith('.py') or '/' in rel: continue
  def symbols(root):
   p=root/rel
   if not p.exists(): return {}
   try:t=ast.parse(p.read_text(encoding='utf-8-sig'))
   except SyntaxError:return {}
   out={}
   def visit(nodes,prefix=''):
    for n in nodes:
     if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
      name=prefix+n.name;out[name]=ast.dump(n,include_attributes=False)
      if isinstance(n,ast.ClassDef):visit(n.body,name+'.')
   visit(t.body);return out
  old,new=symbols(roots['base']),symbols(roots[tag]);rows.append({'donor':tag,'file':rel,'modified_symbols':sorted(k for k in old.keys()&new.keys() if old[k]!=new[k]),'added_symbols':sorted(new.keys()-old.keys()),'removed_symbols':sorted(old.keys()-new.keys())})
(O/'SYMBOL_DELTA.json').write_text(json.dumps(rows,indent=2))
