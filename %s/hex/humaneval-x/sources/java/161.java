import java.util.*;
import java.lang.*;

class Solution {
    /**
    You are given a string s.
    if s[i] is a letter, reverse its case from lower to upper or vise versa,
    otherwise keep it as it is.
    If the string contains no letters, reverse the string.
    The function should return the resulted string.
    Examples
    solve("1234") = "4321"
    solve("ab") = "AB"
    solve("#a@C") = "#A@c"
     */
    public String solve(String s) {
        boolean flag = true;
        StringBuilder new_string = new StringBuilder();
        for (char i : s.toCharArray()) {
            if (Character.isUpperCase(i)) {
                new_string.append(Character.toLowerCase(i));
                flag = false;
            } else if (Character.isLowerCase(i)) {
                new_string.append(Character.toUpperCase(i));
                flag = false;
            } else {
                new_string.append(i);
            }
        }
        if (flag) {
            new_string.reverse();
        }
        return new_string.toString();
    }
}