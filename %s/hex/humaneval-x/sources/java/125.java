import java.util.*;
import java.lang.*;

class Solution {
    /**
    Given a string of words, return a list of words split on whitespace, if no whitespaces exists in the text you
    should split on commas ',' if no commas exists you should return the number of lower-case letters with odd order in the
    alphabet, ord('a') = 0, ord('b') = 1, ... ord('z') = 25
    Examples
    splitWords("Hello world!") == ["Hello", "world!"]
    splitWords("Hello,world!") == ["Hello", "world!"]
    splitWords("abcdef") == 3
     */
    public Object splitWords(String txt) {
        if (txt.contains(" " )) {
            return Arrays.asList(txt.split(" " ));
        } else if (txt.contains("," )) {
            return Arrays.asList(txt.split("[,\s]" ));
        } else {
            int count = 0;
            for (char c : txt.toCharArray()) {
                if (Character.isLowerCase(c) && (c - 'a') % 2 == 1) {
                    count += 1;
                }
            }
            return count;
        }
    }
}