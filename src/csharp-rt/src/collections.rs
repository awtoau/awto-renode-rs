//! C# collection operations whose Rust near-equivalent silently does
//! something else.
//!
//! Most of `System.Collections.Generic` IS a rename — `Queue<T>` is
//! `VecDeque`, `Count` is `len`, `Enqueue` is `push_back` — and those stay
//! templates. One is not, and it was mapped wrongly.
//!
//! `Dictionary<K,V>.Add(key, value)` **throws `ArgumentException` when the key
//! is already present.** The mapping was `{recv}.insert(k, v)`, and
//! `BTreeMap::insert` overwrites and returns the old value. So a C# program
//! that would have crashed on a duplicate key instead keeps running with the
//! second value — a divergence with no observable moment, which is the defect
//! class this project keeps paying for. 86 sites in the cut.
//!
//! The distinction is not pedantic: `Add` and the indexer `d[k] = v` are two
//! different methods in C#, and the indexer IS overwrite-if-present. Mapping
//! both to `insert` erases a difference the source author chose.

use std::collections::BTreeMap;
use std::fmt::Debug;

/// C# `Dictionary<K,V>.Add(key, value)` and `IDictionary<K,V>.Add`.
///
/// > *"ArgumentException — An element with the same key already exists."*
/// > — .NET API reference, `Dictionary<TKey,TValue>.Add`
///
/// Panics on a duplicate key, naming the C# exception, for the reason given in
/// `arith`: D4 has not settled how exceptions are represented, so the choice
/// lives in one place rather than at 86 sites.
///
/// **This is not the indexer.** C# `d[k] = v` overwrites and does not throw;
/// that maps to `insert` directly and needs no function here.
///
/// The map is a `BTreeMap` rather than a `HashMap`, which is a DEVIATION
/// already recorded under `stdlib.iteration_order_note`: C# enumerates a
/// `Dictionary` in an unspecified but in-practice-stable order, Rust's
/// `HashMap` randomises per process, and translated code does iterate
/// dictionaries. `BTreeMap` is deterministic — ordered by key rather than by
/// insertion, so stable rather than identical.
pub fn dict_add<K: Ord + Debug, V>(map: &mut BTreeMap<K, V>, key: K, value: V) {
    if map.contains_key(&key) {
        panic!("System.ArgumentException: An item with the same key has \
                already been added. Key: {key:?}");
    }
    map.insert(key, value);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn add_inserts_a_new_key() {
        let mut m = BTreeMap::new();
        dict_add(&mut m, "a", 1);
        dict_add(&mut m, "b", 2);
        assert_eq!(m.get("a"), Some(&1));
        assert_eq!(m.len(), 2);
    }

    #[test]
    #[should_panic(expected = "System.ArgumentException")]
    fn add_on_a_duplicate_key_names_the_csharp_exception() {
        // `insert` returns Some(old) and carries on. C# throws. This is the
        // whole reason the function exists.
        let mut m = BTreeMap::new();
        dict_add(&mut m, "a", 1);
        dict_add(&mut m, "a", 2);
    }

    #[test]
    fn the_first_value_is_the_one_that_survives_a_would_be_duplicate() {
        // Ordering the check BEFORE the insert matters: a panic after
        // overwriting would leave the map in the state C# never reaches.
        let mut m = BTreeMap::new();
        dict_add(&mut m, "a", 1);
        let caught = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            dict_add(&mut m, "a", 2);
        }));
        assert!(caught.is_err());
        assert_eq!(m.get("a"), Some(&1));
    }

    #[test]
    fn iteration_is_deterministic() {
        // The BTreeMap choice, asserted rather than assumed: a HashMap here
        // would give the trace oracle a different order every run and the
        // failure would read as nondeterminism rather than as a bug.
        let mut m = BTreeMap::new();
        for k in [3, 1, 2] {
            dict_add(&mut m, k, k * 10);
        }
        assert_eq!(m.keys().copied().collect::<Vec<_>>(), vec![1, 2, 3]);
    }
}
