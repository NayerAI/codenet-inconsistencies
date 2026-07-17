import java.util.*;
import java.lang.*;

class Solution {
    /**
    Given an array arr of integers, find the minimum number of elements that
    need to be changed to make the array palindromic. A palindromic array is an array that
    is read the same backwards and forwards. In one change, you can change one element to any other element.

    For example:
    smallestChange(Arrays.asList(1,2,3,5,4,7,9,6)) == 4
    smallestChange(Arrays.asList(1, 2, 3, 4, 3, 2, 2)) == 1
    smallestChange(Arrays.asList(1, 2, 3, 2, 1)) == 0
     */
    public int smallestChange(List<Integer> arr) {
        int ans = 0;
        for (int i = 0; i < arr.size() / 2; i++) {
            if (!Objects.equals(arr.get(i), arr.get(arr.size() - i - 1))) {
                ans += 1;
            }
        }
        return ans;
    }
}