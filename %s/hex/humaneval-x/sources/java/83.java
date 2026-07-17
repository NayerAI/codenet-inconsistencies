import java.util.*;
import java.lang.*;

class Solution {
    /**
    Given a positive integer n, return the count of the numbers of n-digit
    positive integers that start or end with 1.
     */
    public int startsOneEnds(int n) {
        if (n == 1) {
            return 1;
        }
        return 18 * (int) Math.pow(10, n - 2);
    }
}