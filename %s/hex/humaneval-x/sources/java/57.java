import java.util.*;
import java.lang.*;

class Solution {
    /**
    Return True is list elements are monotonically increasing or decreasing.
    >>> monotonic(Arrays.asList(1, 2, 4, 20))
    true
    >>> monotonic(Arrays.asList(1, 20, 4, 10))
    false
    >>> monotonic(Arrays.asList(4, 1, 0, -10))
    true
     */
    public boolean monotonic(List<Integer> l) {
        List<Integer> l1 = new ArrayList<>(l), l2 = new ArrayList<>(l);
        Collections.sort(l1);
        l2.sort(Collections.reverseOrder());
        return l.equals(l1) || l.equals(l2);
    }
}