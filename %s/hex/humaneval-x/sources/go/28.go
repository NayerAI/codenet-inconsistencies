
// Concatenate list of strings into a single string
// >>> Concatenate([])
// ''
// >>> Concatenate(['a', 'b', 'c'])
// 'abc'
func Concatenate(strings []string) string {
    if len(strings) == 0 {
		return ""
	}
	return strings[0] + Concatenate(strings[1:])
}

