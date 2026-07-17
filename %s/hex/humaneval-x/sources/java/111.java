import java.util.*;
import java.lang.*;

class Solution {
    /**
    Given a string representing a space separated lowercase letters, return a dictionary
    of the letter with the most repetition and containing the corresponding count.
    If several letters have the same occurrence, return all of them.

    Example:
    histogram("a b c") == {"a": 1, "b": 1, "c": 1}
    histogram("a b b a") == {"a": 2, "b": 2}
    histogram("a b c a b") == {"a": 2, "b": 2}
    histogram("b b b b a") == {"b": 4}
    histogram("") == {}
     */
    public Map<String, Integer> histogram(String test) {
        Map<String, Integer> dict1 = new HashMap<>();
        List<String> list1 = Arrays.asList(test.split(" " ));
        int t = 0;
        for (String i : list1) {
            if (Collections.frequency(list1, i) > t && !i.isEmpty()) {
                t = Collections.frequency(list1, i);
            }
        }
        if (t > 0) {
            for (String i : list1) {
                if (Collections.frequency(list1, i) == t) {
                    dict1.put(i, t);
                }
            }
        }
        return dict1;
    }
}