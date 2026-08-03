//! C# delegate `+=` (multicast combine).
//!
//! A callback slot translates to a single `Option<Box<dyn FnMut(T)>>`
//! (`rulesdb/rules/csharp_core.json`'s `stdlib.delegates` note), which is
//! faithful for a slot with at most one subscriber. `+=` on that slot needs
//! state this repo does not otherwise keep -- which subscriber(s) are already
//! there -- so it belongs here under
//! `docs/decisions/runtime-is-the-fourth-layer.md` tell #1, not in a template
//! that spells out the combine at every call site.

/// `a += b` on a C# delegate field: call every present subscriber, in the
/// order C# invokes a multicast delegate (existing subscribers first).
pub fn combine_hook<T>(
    a: Option<Box<dyn FnMut(T)>>,
    b: Option<Box<dyn FnMut(T)>>,
) -> Option<Box<dyn FnMut(T)>>
where
    T: Copy + 'static,
{
    match (a, b) {
        (None, None) => None,
        (Some(f), None) => Some(f),
        (None, Some(g)) => Some(g),
        (Some(mut f), Some(mut g)) => Some(Box::new(move |x: T| {
            f(x);
            g(x);
        })),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;
    use std::rc::Rc;

    #[test]
    fn both_none_combines_to_none() {
        let combined: Option<Box<dyn FnMut(u64)>> = combine_hook(None, None);
        assert!(combined.is_none());
    }

    #[test]
    fn one_present_passes_through_unchanged() {
        let calls = Rc::new(RefCell::new(Vec::new()));
        let c = calls.clone();
        let f: Option<Box<dyn FnMut(u64)>> = Some(Box::new(move |x| c.borrow_mut().push(x)));
        let mut combined = combine_hook(f, None);
        combined.as_mut().unwrap()(7);
        assert_eq!(*calls.borrow(), vec![7]);
    }

    #[test]
    fn both_present_calls_both_in_subscription_order() {
        let calls = Rc::new(RefCell::new(Vec::new()));
        let c1 = calls.clone();
        let c2 = calls.clone();
        let f: Option<Box<dyn FnMut(u64)>> = Some(Box::new(move |x| c1.borrow_mut().push(("first", x))));
        let g: Option<Box<dyn FnMut(u64)>> = Some(Box::new(move |x| c2.borrow_mut().push(("second", x))));
        let mut combined = combine_hook(f, g);
        combined.as_mut().unwrap()(3);
        assert_eq!(*calls.borrow(), vec![("first", 3), ("second", 3)]);
    }
}
