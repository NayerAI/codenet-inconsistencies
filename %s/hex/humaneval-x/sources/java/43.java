import java.util.*;
import java.lang.*;

class Solution {
    /**
    pairsSumToZero takes a list of integers as an input.
    it returns True if there are two distinct elements in the list that
    sum to zero, and False otherwise.
    >>> pairsSumToZero(Arrays.asList(1, 3, 5, 0))
    false
    >>> pairsSumToZero(Arrays.asList(1, 3, -2, 1))
    false
    >>> pairsSumToZero(Arrays.asList(1, 2, 3, 7))
    false
    >>> pairsSumToZero(Arrays.asList(2, 4, -5, 3, 5, 7))
    true
    >>> pairsSumToZero(Arrays.asList(1))
    false
     */
    public boolean pairsSumToZero(List<Integer> l) {
        for (int i = 0; i < l.size(); i++) {
            for (int j = i + 1; j < l.size(); j++) {
                if (l.get(i) + l.get(j) == 0) {
                    return true;
                }
            }
        }
        return false;
    }
}