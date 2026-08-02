//! The LINQ operators whose C# meaning a Rust iterator method does not carry.
//!
//! Most of `System.Linq` IS a rename: `Select` is `map`, `Where` is `filter`,
//! `Any` is `any`. Those stay templates. Two do not, and both were wrong in
//! `csharp_core.json` before this module existed:
//!
//! * **`OrderBy` needs a data structure.** Rust iterators cannot sort lazily —
//!   sorting is a whole-sequence operation, so something has to hold the
//!   sequence. The rule mapped it to `{recv}`, the receiver unchanged: a sort
//!   that does not sort, which compiles and replays any trace that does not
//!   observe ordering.
//! * **`First` has an error mode.** C# throws `InvalidOperationException`;
//!   `.next().unwrap()` panics with `called Option::unwrap() on a None value`.
//!   Under D4 those are not the same thing, and a template has nowhere to
//!   record which one was intended.
//!
//! Both are the tells in `docs/decisions/runtime-is-the-fourth-layer.md`: one
//! needs state, the other has an error mode.
//!
//! ## What is deliberately NOT here
//!
//! `Sum`, `Max`, `Min`, `Count`, `Single` and the rest have no function here
//! because they have no caller: no template needs one. A runtime function with
//! no emitting rule is the same mistake as a hand-written peripheral — output
//! that looks finished — with the layers swapped.

/// C# `Enumerable.OrderBy(source, keySelector)`.
///
/// Two properties of the C# operator that the mapping has to preserve:
///
/// * **It is a STABLE sort.** The .NET documentation for `OrderBy` states
///   *"This method performs a stable sort; that is, if the keys of two
///   elements are equal, the order of the elements is preserved."* An unstable
///   sort would be a silent reordering of equal-keyed elements — precisely the
///   behaviourally-inert-looking difference that a replay oracle cannot see.
///   `slice::sort_by_key` is stable, so this is an equivalence, not a
///   narrowing.
/// * **It orders by the KEY, not by the element.** The selector is applied to
///   each element and the results are compared. Discarding the selector and
///   sorting the elements themselves is a different function that usually
///   agrees, which is why it survives review.
///
/// DEVIATION, inherited and already recorded: C# `OrderBy` is lazy and this is
/// eager. That is `stdlib.ienumerable_deviation`, which applies to every
/// sequence this converter materialises, and is not specific to sorting — a
/// sort has to buffer the whole sequence in any case, so nothing is lost here
/// that was not already lost at the `IEnumerable<T>` → `Vec<T>` boundary.
///
/// Returns a concrete iterator so a chained LINQ call composes without the
/// caller knowing a `Vec` happened.
pub fn order_by<T, K, F>(source: impl IntoIterator<Item = T>, mut key: F)
    -> std::vec::IntoIter<T>
where
    K: Ord,
    F: FnMut(&T) -> K,
{
    let mut items: Vec<T> = source.into_iter().collect();
    items.sort_by_key(|item| key(item));
    items.into_iter()
}

/// C# `Enumerable.OrderByDescending(source, keySelector)`.
///
/// Stable, like `OrderBy`: .NET reverses the comparison, not the sequence, so
/// elements with equal keys keep their original relative order rather than
/// being flipped. Reversing the output of a stable ascending sort would NOT be
/// the same function — it reverses ties too.
pub fn order_by_descending<T, K, F>(source: impl IntoIterator<Item = T>, mut key: F)
    -> std::vec::IntoIter<T>
where
    K: Ord,
    F: FnMut(&T) -> K,
{
    let mut items: Vec<T> = source.into_iter().collect();
    items.sort_by(|a, b| key(b).cmp(&key(a)));
    items.into_iter()
}

/// C# `Enumerable.First(source)`.
///
/// Throws `InvalidOperationException("Sequence contains no elements")` on an
/// empty sequence. This panics, and names the exception, for the reason given
/// in `arith`: D4 has not settled how exceptions are represented, so the
/// choice lives in one place with the C# behaviour recorded, rather than as
/// `.unwrap()` at every site where the message would say nothing about C#.
pub fn first<T>(source: impl IntoIterator<Item = T>) -> T {
    match source.into_iter().next() {
        Some(v) => v,
        None => panic!("System.InvalidOperationException: Sequence contains no elements"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn order_by_actually_orders_by_the_key() {
        // The rule this replaces returned the receiver unchanged, so this
        // assertion is the whole point of the module.
        let xs = vec![(3, 'c'), (1, 'a'), (2, 'b')];
        let got: Vec<char> = order_by(xs, |p| p.0).map(|p| p.1).collect();
        assert_eq!(got, vec!['a', 'b', 'c']);
    }

    #[test]
    fn order_by_is_stable_for_equal_keys() {
        // .NET documents OrderBy as a stable sort. An unstable one agrees on
        // every input with distinct keys, so only this case can tell them
        // apart -- and no trace replay would.
        let xs = vec![(1, 'a'), (0, 'x'), (1, 'b'), (0, 'y'), (1, 'c')];
        let got: Vec<char> = order_by(xs, |p| p.0).map(|p| p.1).collect();
        assert_eq!(got, vec!['x', 'y', 'a', 'b', 'c']);
    }

    #[test]
    fn order_by_does_not_sort_by_the_element() {
        // Discarding the key selector and sorting elements is the mistake
        // that usually agrees: here the key ORDER is the reverse of the
        // element order, so the two answers differ.
        let xs = vec![1, 2, 3];
        let got: Vec<i32> = order_by(xs, |v| -v).collect();
        assert_eq!(got, vec![3, 2, 1]);
    }

    #[test]
    fn order_by_composes_as_an_iterator() {
        // A chained LINQ call must not need to know a Vec was built.
        let xs = vec![5, 1, 4, 2];
        let got: Vec<i32> = order_by(xs, |v| *v).filter(|v| v % 2 == 0).collect();
        assert_eq!(got, vec![2, 4]);
    }

    #[test]
    fn order_by_descending_is_stable_too() {
        // Reversing a stable ascending sort would give ['c','b','a', ...],
        // flipping the ties. .NET reverses the COMPARISON, not the sequence.
        let xs = vec![(1, 'a'), (0, 'x'), (1, 'b'), (0, 'y')];
        let got: Vec<char> = order_by_descending(xs, |p| p.0).map(|p| p.1).collect();
        assert_eq!(got, vec!['a', 'b', 'x', 'y']);
    }

    #[test]
    fn order_by_on_an_empty_sequence_is_empty() {
        let xs: Vec<i32> = Vec::new();
        assert_eq!(order_by(xs, |v| *v).count(), 0);
    }

    #[test]
    fn first_returns_the_first_element() {
        assert_eq!(first(vec![7, 8, 9]), 7);
    }

    #[test]
    #[should_panic(expected = "System.InvalidOperationException")]
    fn first_on_empty_names_the_csharp_exception() {
        let xs: Vec<i32> = Vec::new();
        let _ = first(xs);
    }
}
