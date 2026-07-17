import java.util.*;
import java.lang.*;

class Solution {
    /**
    Return the number of times the digit 7 appears in integers less than n which are divisible by 11 or 13.
    >>> fizzBuzz(50)
    0
    >>> fizzBuzz(78)
    2
    >>> fizzBuzz(79)
    3
     */
    public int fizzBuzz(int n) {
        int result = 0;
        for (int i = 1; i < n; i++) {
            if (i % 11 == 0 || i % 13 == 0) {
                char[] digits = String.valueOf(i).toCharArray();
                for (char c : digits) {
                    if (c == '7') {
                        result += 1;
                    }
                }
            }
        }
        return result;
    }
}