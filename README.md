## Direction handling

The compiler emits a single canonical **LEFT** transducer. For **RIGHT** rules,
`snc2fst eval` applies the standard reversal wrapper (reverse input, run the
machine, then reverse output). This keeps compilation consistent while still
supporting both directions at runtime.
