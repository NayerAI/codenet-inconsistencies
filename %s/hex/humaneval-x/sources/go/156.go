import (
    "strings"
)

// Given a positive integer, obtain its roman numeral equivalent as a string,
// and return it in lowercase.
// Restrictions: 1 <= num <= 1000
// 
// Examples:
// >>> IntToMiniRoman(19) == 'xix'
// >>> IntToMiniRoman(152) == 'clii'
// >>> IntToMiniRoman(426) == 'cdxxvi'
func IntToMiniRoman(number int) string {
    num := []int{1, 4, 5, 9, 10, 40, 50, 90,  
           100, 400, 500, 900, 1000}
    sym := []string{"I", "IV", "V", "IX", "X", "XL",  
           "L", "XC", "C", "CD", "D", "CM", "M"}
    i := 12
    res := ""
    for number != 0 {
        div := number / num[i] 
        number %= num[i] 
        for div != 0 {
            res += sym[i] 
            div--
        }
        i--
    }
    return strings.ToLower(res)
}

