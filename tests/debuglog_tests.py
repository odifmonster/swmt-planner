#!/usr/bin/env python

"""White-box coverage of `swmtplanner.debuglog.DebugLog`. See
`tests/spec-files/DEBUGLOG_TEST_SPEC.md`. These tests intentionally inspect the
object's internal state (`_tables`, `_counters`, `_data`) — the schema/link
bookkeeping is the part worth pinning down and there is no public read API."""

import unittest

from swmtplanner.debuglog import DebugLog


def _cols(table_schema):
    """The non-`@` (real) column names of a table schema, in declared order."""
    return [c for c in table_schema if not c.startswith('@')]


def _linked_log():
    """`il`: counter-backed pk `move_id`. `cs`: non-auto pk `summary_id` with a
    foreign key `move_id` onto `il.move_id`."""
    dl = DebugLog(
        il=[('move_id', None), ('iteration_idx', None), ('role', 'rejected')],
        cs=[('summary_id', None), ('move_id', None), ('cost', 0.0)],
    )
    dl.set_pk('il', 'move_id', ctr_name='move_id')
    dl.set_pk('cs', 'summary_id')
    dl.set_fk('cs', 'move_id', 'il', 'move_id')
    return dl


# ===================================================================
# 1. Construction
# ===================================================================

class ConstructionTests(unittest.TestCase):

    def test_schema_built_with_defaults_and_no_keys(self):
        dl = DebugLog(
            il=[('move_id', None), ('role', 'rejected'), ('rank', None)],
            notes=[('text', None)],
        )
        self.assertEqual(set(dl._tables), {'il', 'notes'})
        il = dl._tables['il']
        # '@pk_col_name' present and None; columns in declared order.
        self.assertIsNone(il['@pk_col_name'])
        self.assertEqual(_cols(il), ['move_id', 'role', 'rank'])
        # Each column carries its given default and an unset key_type.
        self.assertEqual(il['move_id'], {'default': None, 'key_type': None})
        self.assertEqual(il['role'], {'default': 'rejected', 'key_type': None})
        self.assertEqual(il['rank'], {'default': None, 'key_type': None})
        self.assertEqual(dl._tables['notes']['text'],
                         {'default': None, 'key_type': None})
        self.assertIsNone(dl._tables['notes']['@pk_col_name'])

    def test_no_counters_and_no_row_data(self):
        dl = DebugLog(il=[('move_id', None)], notes=[('text', None)])
        self.assertEqual(dl._counters.ctr_names, ())
        self.assertEqual(dl._data, {})

    def test_tables_property_lists_names_in_declaration_order(self):
        dl = DebugLog(
            iteration_log=[('move_id', None), ('role', 'rejected')],
            notes=[('text', None)],
        )
        self.assertEqual(dl.tables, ('iteration_log', 'notes'))

    def test_tables_property_unaffected_by_keys_and_rows(self):
        # `tables` reflects the registered tables, not their keys or row data.
        dl = _linked_log()
        before = dl.tables
        self.assertEqual(before, ('il', 'cs'))
        dl.add_row('il', iteration_idx=0)
        dl.add_row('cs', summary_id='1_x', cost=1.0)
        self.assertEqual(dl.tables, before)


# ===================================================================
# 2.1 set_pk — invalid inputs
# ===================================================================

class SetPkInvalidInputTests(unittest.TestCase):

    def setUp(self):
        self.dl = DebugLog(
            il=[('move_id', None), ('iteration_idx', None)],
            cs=[('summary_id', None), ('move_id', None)],
        )

    def test_unknown_table(self):
        with self.assertRaises(KeyError):
            self.dl.set_pk('nope', 'move_id')

    def test_unknown_column(self):
        with self.assertRaises(KeyError):
            self.dl.set_pk('il', 'nope')

    def test_counter_name_already_in_use(self):
        self.dl.set_pk('il', 'move_id', ctr_name='k')
        with self.assertRaises(ValueError):
            self.dl.set_pk('cs', 'summary_id', ctr_name='k')
        # cs got no primary key from the failed call.
        self.assertIsNone(self.dl._tables['cs']['@pk_col_name'])

    def test_column_already_foreign_key(self):
        self.dl.set_pk('il', 'move_id', ctr_name='move_id')
        self.dl.set_fk('cs', 'move_id', 'il', 'move_id')
        with self.assertRaises(ValueError):
            self.dl.set_pk('cs', 'move_id')
        # Unchanged: cs.move_id is still a foreign key; cs has no pk.
        self.assertEqual(self.dl._tables['cs']['move_id']['key_type'],
                         'foreign')
        self.assertIsNone(self.dl._tables['cs']['@pk_col_name'])

    def test_second_primary_key_on_table(self):
        self.dl.set_pk('il', 'move_id', ctr_name='move_id')
        with self.assertRaises(ValueError):
            self.dl.set_pk('il', 'iteration_idx')
        # Unchanged: pk is still move_id; iteration_idx unkeyed.
        self.assertEqual(self.dl._tables['il']['@pk_col_name'], 'move_id')
        self.assertIsNone(self.dl._tables['il']['iteration_idx']['key_type'])

    def test_redeclare_with_different_counter(self):
        self.dl.set_pk('il', 'move_id', ctr_name='move_id')
        with self.assertRaises(ValueError):
            self.dl.set_pk('il', 'move_id', ctr_name='other')

    def test_switch_counter_to_non_counter(self):
        self.dl.set_pk('il', 'move_id', ctr_name='move_id')
        with self.assertRaises(ValueError):
            self.dl.set_pk('il', 'move_id')             # now without a counter

    def test_switch_non_counter_to_counter(self):
        self.dl.set_pk('cs', 'summary_id')              # non-auto pk
        with self.assertRaises(ValueError):
            self.dl.set_pk('cs', 'summary_id', ctr_name='k')


# ===================================================================
# 2.2 set_fk — invalid inputs
# ===================================================================

class SetFkInvalidInputTests(unittest.TestCase):

    def setUp(self):
        self.dl = DebugLog(
            il=[('move_id', None), ('iteration_idx', None)],
            cs=[('summary_id', None), ('move_id', None)],
            other=[('oid', None)],
        )
        self.dl.set_pk('il', 'move_id', ctr_name='move_id')
        self.dl.set_pk('other', 'oid', ctr_name='oid')

    def test_unknown_table_or_column(self):
        with self.assertRaises(KeyError):
            self.dl.set_fk('nope', 'move_id', 'il', 'move_id')
        with self.assertRaises(KeyError):
            self.dl.set_fk('cs', 'nope', 'il', 'move_id')

    def test_unknown_foreign_table_or_column(self):
        with self.assertRaises(KeyError):
            self.dl.set_fk('cs', 'move_id', 'nope', 'move_id')
        with self.assertRaises(KeyError):
            self.dl.set_fk('cs', 'move_id', 'il', 'nope')

    def test_foreign_column_not_a_primary_key(self):
        # il.iteration_idx exists but il's pk is move_id, not it.
        with self.assertRaises(ValueError):
            self.dl.set_fk('cs', 'move_id', 'il', 'iteration_idx')

    def test_foreign_table_has_no_primary_key(self):
        # cs has no pk at all, so nothing in it can be referenced.
        with self.assertRaises(ValueError):
            self.dl.set_fk('il', 'iteration_idx', 'cs', 'summary_id')

    def test_column_already_primary_key(self):
        # il.move_id is il's pk; it cannot also be a foreign key.
        with self.assertRaises(ValueError):
            self.dl.set_fk('il', 'move_id', 'other', 'oid')

    def test_column_already_fk_to_different_referent(self):
        self.dl.set_fk('cs', 'move_id', 'il', 'move_id')
        with self.assertRaises(ValueError):
            self.dl.set_fk('cs', 'move_id', 'other', 'oid')
        # Unchanged: still linked to il's counter.
        self.assertEqual(self.dl._tables['cs']['move_id']['ctr_name'],
                         'move_id')


# ===================================================================
# 3. Schema frozen once rows exist
# ===================================================================

class SchemaFreezeTests(unittest.TestCase):

    def setUp(self):
        self.dl = DebugLog(
            il=[('move_id', None), ('iteration_idx', None)],
            cs=[('summary_id', None), ('move_id', None)],
        )
        self.dl.set_pk('il', 'move_id', ctr_name='move_id')
        self.dl.add_row('il', iteration_idx=0)          # il now holds row data

    def test_set_pk_after_rows_raises(self):
        with self.assertRaises(ValueError):
            self.dl.set_pk('il', 'iteration_idx')

    def test_set_fk_after_rows_raises(self):
        with self.assertRaises(ValueError):
            self.dl.set_fk('il', 'iteration_idx', 'il', 'move_id')

    def test_identical_redeclaration_after_rows_still_raises(self):
        # Without rows this would be a silent no-op; the row-data guard fires
        # before the no-op check, so it raises.
        with self.assertRaises(ValueError):
            self.dl.set_pk('il', 'move_id', ctr_name='move_id')


# ===================================================================
# 4. Valid schema updates
# ===================================================================

class ValidSchemaUpdateTests(unittest.TestCase):

    def setUp(self):
        self.dl = DebugLog(
            il=[('move_id', None), ('iteration_idx', None)],
            cs=[('summary_id', None), ('move_id', None)],
        )

    def test_set_pk_with_counter(self):
        self.dl.set_pk('il', 'move_id', ctr_name='move_id')
        il = self.dl._tables['il']
        self.assertEqual(il['@pk_col_name'], 'move_id')
        self.assertEqual(il['move_id']['key_type'], 'primary')
        self.assertEqual(il['move_id']['ctr_name'], 'move_id')
        self.assertIn('move_id', self.dl._counters.ctr_names)

    def test_set_pk_without_counter(self):
        self.dl.set_pk('cs', 'summary_id')
        cs = self.dl._tables['cs']
        self.assertEqual(cs['@pk_col_name'], 'summary_id')
        self.assertEqual(cs['summary_id']['key_type'], 'primary')
        self.assertNotIn('ctr_name', cs['summary_id'])
        self.assertEqual(self.dl._counters.ctr_names, ())

    def test_set_fk_to_counter_backed_pk(self):
        self.dl.set_pk('il', 'move_id', ctr_name='move_id')
        self.dl.set_fk('cs', 'move_id', 'il', 'move_id')
        fk = self.dl._tables['cs']['move_id']
        self.assertEqual(fk['key_type'], 'foreign')
        self.assertEqual(fk['ctr_name'], 'move_id')
        self.assertNotIn('table_name', fk)

    def test_set_fk_to_non_auto_pk(self):
        self.dl.set_pk('il', 'move_id')                 # non-auto pk
        self.dl.set_fk('cs', 'move_id', 'il', 'move_id')
        fk = self.dl._tables['cs']['move_id']
        self.assertEqual(fk['key_type'], 'foreign')
        self.assertEqual(fk['table_name'], 'il')
        self.assertNotIn('ctr_name', fk)

    def test_idempotent_redeclaration_is_noop(self):
        self.dl.set_pk('il', 'move_id', ctr_name='move_id')
        self.dl.set_fk('cs', 'move_id', 'il', 'move_id')
        before_il = dict(self.dl._tables['il']['move_id'])
        before_fk = dict(self.dl._tables['cs']['move_id'])
        # Identical re-declarations: no error, no change, no duplicate counter.
        self.dl.set_pk('il', 'move_id', ctr_name='move_id')
        self.dl.set_fk('cs', 'move_id', 'il', 'move_id')
        self.assertEqual(self.dl._tables['il']['move_id'], before_il)
        self.assertEqual(self.dl._tables['cs']['move_id'], before_fk)
        self.assertEqual(self.dl._counters.ctr_names, ('move_id',))


# ===================================================================
# 5. add_row and auto-increment
# ===================================================================

class AddRowTests(unittest.TestCase):

    def setUp(self):
        self.dl = DebugLog(
            il=[('move_id', None), ('iteration_idx', None), ('role', 'rejected')],
            kv=[('id', None), ('val', 0)],
            notes=[('text', None)],
        )
        self.dl.set_pk('il', 'move_id', ctr_name='move_id')
        self.dl.set_pk('kv', 'id')                      # non-auto pk

    def test_lazy_creation(self):
        self.assertNotIn('il', self.dl._data)
        self.dl.add_row('il', iteration_idx=0)
        self.assertIn('il', self.dl._data)

    def test_counter_pk_auto_increments(self):
        self.assertEqual(self.dl.add_row('il', iteration_idx=0), 1)
        self.assertEqual(self.dl.add_row('il', iteration_idx=1), 2)
        self.assertEqual(self.dl.add_row('il', iteration_idx=2), 3)
        self.assertEqual(self.dl.get_last_pk_val('il'), 3)
        self.assertEqual(set(self.dl._data['il']['rows']), {1, 2, 3})
        self.assertEqual(self.dl._data['il']['last_pk_val'], 3)

    def test_row_layout_and_defaults(self):
        mid = self.dl.add_row('il', iteration_idx=5)    # role unset -> default
        data = self.dl._data['il']
        # col_map: non-pk columns in declared order, pk excluded.
        self.assertEqual(data['col_map'], {'iteration_idx': 0, 'role': 1})
        self.assertEqual(data['rows'][mid], [5, 'rejected'])

    def test_non_auto_pk_supplied(self):
        self.assertEqual(self.dl.add_row('kv', id='x', val=9), 'x')
        self.assertEqual(self.dl.add_row('kv', id='y'), 'y')   # val -> default 0
        self.assertEqual(self.dl._data['kv']['rows']['x'], [9])
        self.assertEqual(self.dl._data['kv']['rows']['y'], [0])
        self.assertEqual(self.dl.get_last_pk_val('kv'), 'y')

    def test_auto_pk_must_not_be_supplied(self):
        with self.assertRaises(ValueError):
            self.dl.add_row('il', move_id=99, iteration_idx=0)

    def test_non_auto_pk_must_be_supplied(self):
        with self.assertRaises(ValueError):
            self.dl.add_row('kv', val=9)

    def test_key_less_table(self):
        self.assertIsNone(self.dl.add_row('notes', text='hi'))
        data = self.dl._data['notes']
        self.assertEqual(data['rows'], [{'text': 'hi'}])
        self.assertIn('columns', data)
        self.assertNotIn('col_map', data)               # no pk machinery
        self.assertNotIn('last_pk_val', data)


# ===================================================================
# 6. update_row
# ===================================================================

class UpdateRowTests(unittest.TestCase):

    def setUp(self):
        self.dl = _linked_log()
        self.mid = self.dl.add_row('il', iteration_idx=0)         # move_id == 1
        self.dl.add_row('cs', summary_id='s1', cost=1.0)          # move_id fk -> 1
        self.dl.add_row('il', iteration_idx=1)                    # counter -> 2

    def test_patches_named_columns_only(self):
        self.dl.update_row('il', self.mid, role='committed')
        row = self.dl._data['il']['rows'][self.mid]
        # iteration_idx (col 0) untouched, role (col 1) patched.
        self.assertEqual(row, [0, 'committed'])

    def test_fk_not_named_keeps_value(self):
        # move_id was linked to 1 at add time; patching only cost leaves it.
        self.dl.update_row('cs', 's1', cost=9.0)
        self.assertEqual(self.dl._data['cs']['rows']['s1'], [1, 9.0])

    def test_fk_passed_none_relinks(self):
        # explicit None re-links to the current counter value (now 2).
        self.dl.update_row('cs', 's1', move_id=None)
        self.assertEqual(self.dl._data['cs']['rows']['s1'][0], 2)

    def test_fk_passed_value_is_used(self):
        self.dl.update_row('cs', 's1', move_id=7)
        self.assertEqual(self.dl._data['cs']['rows']['s1'][0], 7)

    def test_no_primary_key_raises(self):
        dl = DebugLog(notes=[('text', None)])
        dl.add_row('notes', text='x')
        with self.assertRaises(ValueError):
            dl.update_row('notes', 0, text='y')

    def test_unknown_pk_value_raises(self):
        with self.assertRaises(KeyError):
            self.dl.update_row('il', 999, role='x')

    def test_unknown_column_raises(self):
        with self.assertRaises(KeyError):
            self.dl.update_row('il', self.mid, nope='x')

    def test_cannot_update_primary_key_column(self):
        with self.assertRaises(ValueError):
            self.dl.update_row('il', self.mid, move_id=2)


# ===================================================================
# 7. A foreign key does not advance its counter
# ===================================================================

class ForeignKeyCounterTests(unittest.TestCase):

    def test_fk_reads_current_counter_without_advancing(self):
        dl = _linked_log()
        dl.add_row('il', iteration_idx=0)               # mints move_id 1
        self.assertEqual(dl._counters('move_id'), 1)
        dl.add_row('cs', summary_id='s1')               # fk reads current
        self.assertEqual(dl._data['cs']['rows']['s1'][0], 1)   # linked to 1
        self.assertEqual(dl._counters('move_id'), 1)    # NOT advanced
        # The counter only advances on the next il add_row.
        self.assertEqual(dl.add_row('il', iteration_idx=1), 2)


# ===================================================================
# 8. Multiple foreign keys to one primary key
# ===================================================================

class MultipleForeignKeyTests(unittest.TestCase):

    def setUp(self):
        self.dl = DebugLog(
            il=[('move_id', None), ('iteration_idx', None)],
            cs=[('summary_id', None), ('move_id', None)],
            cs2=[('sid2', None), ('move_id', None)],
        )
        self.dl.set_pk('il', 'move_id', ctr_name='move_id')
        self.dl.set_pk('cs', 'summary_id')
        self.dl.set_pk('cs2', 'sid2')
        self.dl.set_fk('cs', 'move_id', 'il', 'move_id')
        self.dl.set_fk('cs2', 'move_id', 'il', 'move_id')

    def test_both_fks_inherit_same_counter(self):
        self.assertEqual(self.dl._tables['cs']['move_id']['ctr_name'], 'move_id')
        self.assertEqual(self.dl._tables['cs2']['move_id']['ctr_name'], 'move_id')

    def test_both_link_to_same_current_pk(self):
        self.dl.add_row('il', iteration_idx=0)          # move_id 1
        self.dl.add_row('cs', summary_id='a')
        self.dl.add_row('cs2', sid2='b')
        self.assertEqual(self.dl._data['cs']['rows']['a'][0], 1)
        self.assertEqual(self.dl._data['cs2']['rows']['b'][0], 1)


if __name__ == '__main__':
    unittest.main()
