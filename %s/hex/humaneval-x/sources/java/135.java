import java.util.*;
import java.lang.*;

class Solution {
    /**
    Create a function which returns the largest index of an element which
    is not greater than or equal to the element immediately preceding it. If
    no such element exists then return -1. The given array will not contain
    duplicate values.

    Examples:
    canArrange(Arrays.asList(1,2,4,3,5)) = 3
    canArrange(Arrays.asList(1,2,3)) = -1
     */
    public int canArrange(List<Integer> arr) {
        int ind = -1, i = 1;
        while (i < arr.size()) {
            if (arr.get(i) < arr.get(i - 1)) {
                ind = i;
            }
            i += 1;
        }
        return ind;
    }
}