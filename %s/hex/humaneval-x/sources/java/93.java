import java.util.*;
import java.lang.*;

class Solution {
    /**
    Write a function that takes a message, and encodes in such a
    way that it swaps case of all letters, replaces all vowels in
    the message with the letter that appears 2 places ahead of that
    vowel in the english alphabet.
    Assume only letters.

    Examples:
    >>> encode("test")
    "TGST"
    >>> encode("This is a message")
    "tHKS KS C MGSSCGG"
     */
    public String encode(String message) {
        String vowels = "aeiouAEIOU";
        StringBuilder sb = new StringBuilder();
        for (char c : message.toCharArray()) {
            char ch = c;
            if (Character.isUpperCase(ch)) {
                ch = Character.toLowerCase(ch);
                if (vowels.indexOf(ch) != -1) {
                    ch = (char) ('a' + ((ch - 'a' + 28) % 26));
                }
            } else if (Character.isLowerCase(ch)) {
                ch = Character.toUpperCase(ch);
                if (vowels.indexOf(ch) != -1) {
                    ch = (char) ('A' + ((ch - 'A' + 28) % 26));
                }
            }
            sb.append(ch);
        }
        return sb.toString();
    }
}