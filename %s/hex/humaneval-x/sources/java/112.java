import java.util.*;
import java.lang.*;

class Solution {
    /**
    Task
    We are given two strings s and c, you have to deleted all the characters in s that are equal to any character in c
    then check if the result string is palindrome.
    A string is called palindrome if it reads the same backward as forward.
    You should return a tuple containing the result string and true/false for the check.
    Example
    For s = "abcde", c = "ae", the result should be ("bcd",false)
    For s = "abcdef", c = "b"  the result should be ("acdef",false)
    For s = "abcdedcba", c = "ab", the result should be ("cdedc",true)
     */
    public List<Object> reverseDelete(String s, String c) {
        StringBuilder sb = new StringBuilder();
        for (char ch : s.toCharArray()) {
            if (c.indexOf(ch) == -1) {
                sb.append(ch);
            }
        }
        return Arrays.asList(sb.toString(), sb.toString().equals(sb.reverse().toString()));
    }
}