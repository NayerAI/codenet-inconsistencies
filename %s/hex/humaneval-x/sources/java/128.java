import java.util.*;
import java.lang.*;

class Solution {
    /**
    You are given an array arr of integers and you need to return
    sum of magnitudes of integers multiplied by product of all signs
    of each number in the array, represented by 1, -1 or 0.
    Note: return None for empty arr.

    Example:
    >>> prodSigns(Arrays.asList(1, 2, 2, -4)) == -9
    >>> prodSigns(Arrays.asList(0, 1)) == 0
    >>> prodSigns(Arrays.asList()) == None
     */
    public Optional<Integer> prodSigns(List<Integer> arr) {
        if (arr.size() == 0) {
            return Optional.empty();
        }
        if (arr.contains(0)) {
            return Optional.of(0);
        }
        int prod = (int) (-2 * (arr.stream().filter(p -> p < 0).count() % 2) + 1);
        return Optional.of(prod * (arr.stream().map(Math::abs).reduce(Integer::sum)).get());
    }
}