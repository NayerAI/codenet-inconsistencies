import java.util.*;
import java.lang.*;

class Solution {
    /**
    Write a function that takes an array of numbers as input and returns
    the number of elements in the array that are greater than 10 and both
    first and last digits of a number are odd (1, 3, 5, 7, 9).
    For example:
    specialFilter(Arrays.asList(15, -73, 14, -15)) => 1
    specialFilter(Arrays.asList(33, -2, -3, 45, 21, 109)) => 2
     */
    public int specialFilter(List<Integer> nums) {
        int count = 0;
        for (int num : nums) {
            if (num > 10) {
                String odd_digits = "13579";
                String number_as_string = String.valueOf(num);
                if (odd_digits.indexOf(number_as_string.charAt(0)) != -1 && odd_digits.indexOf(number_as_string.charAt(number_as_string.length() - 1)) != -1) {
                    count += 1;
                }
            }
        }
        return count;
    }
}