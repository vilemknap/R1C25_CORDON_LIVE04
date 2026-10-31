"""Full same-mode geometry proof without scratch SQLite writes.

Control flow mirrors the pinned TwoModeRouteCollector.add_geometry parser;
the independent original collector remains the acceptance oracle. Only the
sink differs: compare each finished route against existing representative SQL.
Memory is O(route count) plus ONE route, never all link occurrences.
"""
from __future__ import annotations
import hashlib
import struct
import sys
from .common import parent_module

ALGORITHM = 'CORDON_STREAM_GEOMETRY_EXACT_V1'
SCHEMA = 'CORDON_FULL_GEOMETRY_PROOF_V2'

class ReferenceGeometry:
    def __init__(self, collector, mode):
        self.collector=collector;self.mode=mode
        two=parent_module('r1_15a2_two_mode_v238')
        self.error=two.SupplyContractError
        if mode not in collector.mode_audits or not collector.mode_audits[mode].get('geometry_complete'):
            raise self.error('REFERENCE_GEOMETRY_NOT_COMPLETE')
        self.index={}
        legacy=hashlib.sha256();canonical=hashlib.sha256()
        for gid,o,d,p,n,h,kind in collector.db.execute(
                'SELECT gid,orig,dest,path_index,edge_count,sequence_sha256,geometry_kind '
                'FROM geometry WHERE mode=? ORDER BY orig,dest,path_index',(mode,)):
            if n is None or h is None or kind is None:
                raise self.error('REFERENCE_GEOMETRY_NOT_COMPLETE')
            key=(o,d,p);self.index[key]=(gid,n,h,kind)
            legacy.update(struct.pack('<III',*key));legacy.update(h.encode('ascii'))
            b=kind.encode('ascii');canonical.update(struct.pack('<IIIII',*key,n,len(b)))
            canonical.update(b);canonical.update(bytes.fromhex(h))
        self.legacy_digest=legacy.hexdigest();self.canonical_digest=canonical.hexdigest()
        self.lookup=collector.db.cursor()

    def close(self):
        self.lookup.close()

    def verify(self, raw_rows, dseg, *, telemetry=None):
        c=self.collector;two=parent_module('r1_15a2_two_mode_v238')
        _id,_filled,_packed=two._id,two._filled,two._packed
        key_map=self.index;seen=set();parent=None;seq_ids=[];last_end=None
        raw_count=child_count=zero_inter=zero_intra=0
        # add_parents already proved exact same-mode parent keys. Verify that
        # the selected segment still has one volume row for every reference key.
        cnt=c.db.execute('SELECT COUNT(*) FROM volumes v JOIN geometry g ON v.gid=g.gid '
                         'WHERE g.mode=? AND v.dseg=?',(self.mode,dseg)).fetchone()[0]
        if cnt!=len(key_map):
            raise self.error('FULL_PARENT_KEYS_DIFFER:'+dseg)

        def fail(message):
            # Keep original error class/code; enrich control evidence, not parsing.
            c.control.state['diagfast_failure']={'dseg':dseg,'mode':self.mode,
                'parent_key':list(parent) if parent else None,'raw_row':raw_count,
                'code':message,'algorithm':ALGORITHM}
            raise self.error(message)

        def finish_route():
            nonlocal zero_inter,zero_intra
            if parent is None:return
            if parent not in key_map or parent in seen:
                fail('ORPHAN_OR_REPEATED_GEOMETRY_PARENT:%r' % (parent,))
            kind='LINK_SEQUENCE'
            if not seq_ids:
                if parent[0]!=parent[1]:
                    zero_inter+=1;kind='ZERO_LINK_INTERZONAL_NO_ADDVAL1_EFFECT'
                else:
                    zero_intra+=1;kind='ZERO_LINK_INTRAZONAL_NO_ADDVAL1_EFFECT'
            gid,n,h,expected_kind=key_map[parent]
            blob=_packed(seq_ids)
            actual_hash=hashlib.sha256(blob).hexdigest()
            if n!=len(seq_ids) or h!=actual_hash or kind!=expected_kind:
                fail('FULL_SAME_MODE_GEOMETRY_DIFFERS_USE_PER_DSEG_GEOMETRY_DESIGN:'+repr(parent))
            # SHA is a locator/check, not a replacement for exact byte equality.
            expected=self.lookup.execute('SELECT edge_ids FROM geometry WHERE gid=?',(gid,)).fetchone()
            if expected is None or expected[0] is None or expected[0]!=blob:
                fail('FULL_SAME_MODE_GEOMETRY_BLOB_DIFFERS:'+repr(parent))
            seen.add(parent)
            if len(seen)%int(c.settings['commit_routes'])==0:
                c.control.checkpoint('FULL_GEOMETRY_STREAM_CHECK',mode=self.mode,dseg=dseg,
                    geometry_routes=len(seen),raw_rows=raw_count,link_children=child_count)
                c.check_resources()

        for raw in raw_rows:
            raw_count+=1
            if raw_count>int(c.settings['max_geometry_rows_per_mode']):
                fail('GEOMETRY_ROW_BUDGET_EXCEEDED')
            if len(raw)!=7:fail('GEOMETRY_ROW_SCHEMA_MISMATCH')
            supplied_parent=tuple(_filled(x) for x in raw[:3])
            supplied_link=tuple(_filled(x) for x in raw[3:])
            if not any(supplied_link):
                if not all(supplied_parent):fail('INCOMPLETE_GEOMETRY_PARENT')
                next_parent=tuple(_id(x) for x in raw[:3])
                finish_route()
                parent=next_parent;seq_ids=[];last_end=None
                if parent not in key_map or parent in seen:fail('UNKNOWN_OR_REOPENED_GEOMETRY_PARENT')
                continue
            if not all(supplied_link):fail('INCOMPLETE_GEOMETRY_CHILD')
            if all(supplied_parent):
                k=tuple(_id(x) for x in raw[:3])
                if k!=parent:
                    finish_route()
                    parent=k;seq_ids=[];last_end=None
                    if parent not in key_map or parent in seen:fail('UNKNOWN_OR_REOPENED_FLAT_PARENT')
            elif any(supplied_parent):
                if parent is None or any(s and _id(raw[j])!=parent[j] for j,s in enumerate(supplied_parent)):
                    fail('CONFLICTING_PARTIAL_GEOMETRY_PARENT')
            if parent is None:fail('ORPHAN_GEOMETRY_CHILD')
            idx=_id(raw[3]);key=tuple(_id(x) for x in raw[4:])
            if idx!=len(seq_ids)+1:fail('GEOMETRY_LINK_INDEX_NOT_CONTIGUOUS')
            if last_end is not None and last_end!=key[1]:fail('DISCONNECTED_OFFICIAL_PATH_LINK_SEQUENCE')
            if key not in c.edge_ids:fail('PATH_EDGE_NOT_IN_LIVE_NETWORK:%r' % (key,))
            seq_ids.append(c.edge_ids[key]);last_end=key[2];child_count+=1
            if len(seq_ids)>int(c.settings['max_links_per_path']):fail('SINGLE_ROUTE_LENGTH_BUDGET_EXCEEDED')
        finish_route()
        if seen!=set(key_map):fail('GEOMETRY_PARENT_COVERAGE_INCOMPLETE')
        c.control.checkpoint('FULL_GEOMETRY_STREAM_COMPLETE',force=True,mode=self.mode,dseg=dseg,
            geometry_routes=len(seen),link_children=child_count)
        c.check_resources(force=True)
        if telemetry:
            telemetry.count('full_stream_proofs')
            telemetry.count('proof_geometry_rows',raw_count)
            telemetry.count('proof_link_children',child_count)
            telemetry.count('proof_routes',len(seen))
            telemetry.count('scratch_sqlite_bytes_written',0)
        return {'schema':SCHEMA,'algorithm_version':ALGORITHM,'dseg':dseg,
            'mode':self.mode,'check':'FULL_SAME_MODE_MATCH','verification':'FULL_STREAM_EXACT_BYTES',
            'source_status':'FULL_REPRESENTATIVE_FROM_ORIGINAL_COLLECTOR',
            'geometry_routes':len(seen),'geometry_raw_rows':raw_count,'geometry_link_children':child_count,
            'zero_link_interzonal_paths':zero_inter,'zero_link_intrazonal_paths':zero_intra,
            'representative_geometry_sha256':self.legacy_digest,
            'canonical_geometry_sha256':self.canonical_digest,
            'all_parent_keys_including_zero_volume':True,'packed_bytes_compared':True,
            'scratch_sqlite_created':False,'scratch_sqlite_bytes_written':0}


def verify_same_mode(collector,mode,dseg,rows,telemetry):
    old=getattr(collector,'_diagfast_reference',None)
    if old is None or old.mode!=mode:
        if old is not None:old.close()
        with telemetry.span('CAPTURE_PROOF_REFERENCE_INDEX'):
            old=ReferenceGeometry(collector,mode)
        collector._diagfast_reference=old
    with telemetry.span('CAPTURE_PROOF_PARSE'):
        return old.verify(rows,dseg,telemetry=telemetry)


def close_reference(collector,control):
    """Do not replace an existing parser/COM exception with cleanup failure."""
    ref=getattr(collector,'_diagfast_reference',None)
    collector._diagfast_reference=None
    if ref is None:return
    primary=sys.exc_info()[0] is not None
    try:ref.close()
    except Exception as exc:
        if not primary:raise
        from .io import exception_text
        control.state.setdefault('cleanup_errors',[]).append(exception_text(exc))
