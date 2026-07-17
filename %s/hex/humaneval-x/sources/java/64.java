import java.util.*;
import java.lang.*;

class Solution {
    /**
    Write a function vowelsCount which takes a string representing
    a word as input and returns the number of vowels in the string.
    Vowels in this case are 'a', 'e', 'i', 'o', 'u'. Here, 'y' is also a
    vowel, but only when it is at the end of the given word.

    Example:
    >>> vowelsCount("abcde")
    2
    >>> vowelsCount("ACEDY")
    3
     */
    public int vowelsCount(String s) {
        String vowels = "aeiouAEIOU";
        int n_vowels = 0;
        for (char c : s.toCharArray()) {
            if (vowels.indexOf(c) != -1) {
                n_vowels += 1;
            }
        }
        if (s.charAt(s.length() - 1) == 'y' || s.charAt(s.length() - 1) == 'Y') {
            n_vowels += 1;
        }
        return n_vowels;
    }
}