Tutorial
========

This page walks through a minimal end-to-end run: initialize sample files,
validate them, compile a rule, and evaluate input words.

Install
-------

Create and activate an environment, then install:

.. code-block:: bash

   python -m venv .venv
   source .venv/bin/activate
   python -m pip install -e .

Conda + Pynini
--------------

If you want the Pynini backend, use conda so `Pynini/pywrapfst` is available:

.. code-block:: bash

   conda create -n snc2fst python=3.12
   conda activate snc2fst
   conda install -c conda-forge pynini
   python -m pip install -e .

Initialize Project
------------------

Generate example alphabet, rules, and input files:

.. code-block:: bash

   snc2fst init samples/

Validate Rules + Input
----------------------

Validation requires the alphabet:

.. code-block:: bash

   snc2fst validate samples/rules.json --alphabet samples/alphabet.csv
   snc2fst validate samples/input.json --kind input --alphabet samples/alphabet.csv

Compile a Rule
--------------

Compile a rule to AT&T and symbol table files:

.. code-block:: bash

   snc2fst compile samples/rules.json samples/rule.att --alphabet samples/alphabet.csv

Write a binary FST alongside the AT&T output:

.. code-block:: bash

   snc2fst compile samples/rules.json samples/rule.att --alphabet samples/alphabet.csv --fst

Evaluate Input
--------------

Evaluate input words with the reference evaluator:

.. code-block:: bash

   snc2fst eval samples/rules.json samples/input.json --alphabet samples/alphabet.csv --output samples/out.json

Use the Pynini backend and compare against the reference:

.. code-block:: bash

   snc2fst eval samples/rules.json samples/input.json --alphabet samples/alphabet.csv --output samples/out.json --pynini --compare

Out DSL Quick Reference
-----------------------

The ``out`` field builds a **feature bundle** from ``INR`` (the target segment)
and ``TRM`` (the last triggering segment). The result is the rewritten bundle.

Core operators:

* ``(bundle (+ F) (- G) ...)`` builds a literal feature bundle.
* ``(proj X (F1 F2 ...))`` keeps only the listed features from ``X``.
* ``(proj X *)`` keeps **all** features from ``X`` (full alphabet).
* ``(unify A B)`` left-biased unification (adds features from ``B`` not in ``A``).
* ``(subtract A B)`` removes features from ``A`` that appear in ``B``.

Some common patterns:

* **Replace search-initiator with a specific segment**

  .. code-block:: none

     (bundle (+ Back) (+ Round) ...)

* **Copy search-terminator feature into the search-initiator (α-notation)**

  .. code-block:: none

     (unify INR (proj TRM (Back)))

* **Copy multiple features (α-notation on multiple features)**

  .. code-block:: none

     (unify INR (proj TRM (Back Round)))

* **Unify INR with static feature bundle**

  .. code-block:: none

     (unify INR (bundle (- Back)))

* **Copy a full segment (will produce a huge FST)**

  .. code-block:: none

     (proj TRM *)

Remember: ``INR``/``TRM`` are restricted to rule-visible features unless you
use ``proj *`` to expand to the full alphabet.

Tip: Use ``--rule-id`` to select a single rule when multiple rules are present.
