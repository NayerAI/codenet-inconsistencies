import java.util.*;
import java.lang.*;

class Solution {
    /**
    Given an array of integers nums, find the minimum sum of any non-empty sub-array
    of nums.
    Example
    minSubArraySum(Arrays.asList(2, 3, 4, 1, 2, 4)) == 1
    minSubArraySum(Arrays.asList(-1, -2, -3)) == -6
     */
    public int minSubArraySum(List<Integer> nums) {
        int minSum = Integer.MAX_VALUE;
        int sum = 0;
        for (Integer num : nums) {
            sum += num;
            if (minSum > sum) {
                minSum = sum;
            }
            if (sum > 0) {
                sum = 0;
            }
        }
        return minSum;
    }
}