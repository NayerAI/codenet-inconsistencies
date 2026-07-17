import java.util.*;
import java.lang.*;

class Solution {
    /**
    The Fib4 number sequence is a sequence similar to the Fibbonacci sequnece that's defined as follows:
    fib4(0) -> 0
    fib4(1) -> 0
    fib4(2) -> 2
    fib4(3) -> 0
    fib4(n) -> fib4(n-1) + fib4(n-2) + fib4(n-3) + fib4(n-4).
    Please write a function to efficiently compute the n-th element of the fib4 number sequence.  Do not use recursion.
    >>> fib4(5)
    4
    >>> fib4(6)
    8
    >>> fib4(7)
    14
     */
    public int fib4(int n) {
        List<Integer> results = new ArrayList<>();
        results.add(0);
        results.add(0);
        results.add(2);
        results.add(0);
        if (n < 4) {
            return results.get(n);
        }

        for (int i = 4; i <= n; i++) {
            results.add(results.get(0) + results.get(1) + results.get(2) + results.get(3));
            results.remove(0);
        }
        return results.get(3);
    }
}