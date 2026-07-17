import java.util.*;
import java.lang.*;

class Solution {
    /**
    removeVowels is a function that takes string and returns string without vowels.
    >>> removeVowels("")
    ""
    >>> removeVowels("abcdef\nghijklm")
    "bcdf\nghjklm"
    >>> removeVowels("abcdef")
    "bcdf"
    >>> removeVowels("aaaaa")
    ""
    >>> removeVowels("aaBAA")
    "B"
    >>> removeVowels("zbcd")
    "zbcd"
     */
    public String removeVowels(String text) {
        StringBuilder sb = new StringBuilder();
        for (char ch : text.toCharArray()) {
            if ("aeiou".indexOf(Character.toLowerCase(ch)) == -1) {
                sb.append(ch);
            }
        }
        return sb.toString();
    }
}