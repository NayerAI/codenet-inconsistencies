import java.util.*;
import java.lang.*;

class Solution {
    /**
    You are given a word. Your task is to find the closest vowel that stands between
    two consonants from the right side of the word (case sensitive).

    Vowels in the beginning and ending doesn't count. Return empty string if you didn't
    find any vowel met the above condition.

    You may assume that the given string contains English letter only.

    Example:
    getClosestVowel("yogurt") ==> "u"
    getClosestVowel("FULL") ==> "U"
    getClosestVowel("quick") ==> ""
    getClosestVowel("ab") ==> ""
     */
    public String getClosestVowel(String word) {
        if (word.length() < 3) {
            return "";
        }

        String vowels = "aeiouAEIOU";
        for (int i = word.length() - 2; i > 0; i--) {
            if (vowels.indexOf(word.charAt(i)) != -1 && vowels.indexOf(word.charAt(i + 1)) == -1 && vowels.indexOf(word.charAt(i - 1)) == -1) {
                return String.valueOf(word.charAt(i));
            }
        }
        return "";
    }
}