import java.util.*;
import java.lang.*;

class Solution {
    /**
    Given list of numbers (of at least two elements), apply a linear transform to that list,
    such that the smallest number will become 0 and the largest will become 1
    >>> rescaleToUnit(Arrays.asList(1.0, 2.0, 3.0, 4.0, 5.0))
    [0.0, 0.25, 0.5, 0.75, 1.0]
     */
    public List<Double> rescaleToUnit(List<Double> numbers) {
        double min_number = Collections.min(numbers);
        double max_number = Collections.max(numbers);
        List<Double> result = new ArrayList<>();
        for (double x : numbers) {
            result.add((x - min_number) / (max_number - min_number));
        }
        return result;
    }
}