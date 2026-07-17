import java.util.*;
import java.lang.*;
import java.util.stream.Collectors;

class Solution {
    /**
    Filter an input list of strings only for ones that start with a given prefix.
    >>> filterByPrefix(List.of(), "a")
    []
    >>> filterByPrefix(Arrays.asList("abc", "bcd", "cde", "array"), "a")
    ["abc", "array"]
     */
    public List<String> filterByPrefix(List<String> strings, String prefix) {
        return strings.stream().filter(p -> p.startsWith(prefix)).collect(Collectors.toList());
    }
}