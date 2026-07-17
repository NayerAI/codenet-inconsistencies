import (
    "strings"
)

// Given a string, find out how many distinct characters (regardless of case) does it consist of
// >>> CountDistinctCharacters('xyzXYZ')
// 3
// >>> CountDistinctCharacters('Jerry')
// 4
func CountDistinctCharacters(str string) int{
    lower := strings.ToLower(str)
	count := 0
	set := make(map[rune]bool)
	for _, i := range lower {
		if set[i] == true {
			continue
		} else {
			set[i] = true
			count++
		}
	}
	return count
}


