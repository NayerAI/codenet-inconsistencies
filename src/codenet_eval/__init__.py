"""CodeNet cross-language inconsistency evaluation framework.

This package downloads (a subset of) IBM Project CodeNet, samples problems that
are solved in several programming languages, and asks an LLM (via OpenRouter)
whether the per-language implementations are behaviourally consistent -- and if
not, to produce a concrete input that makes them diverge.  The proposed inputs
can optionally be verified by actually executing both programs.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
