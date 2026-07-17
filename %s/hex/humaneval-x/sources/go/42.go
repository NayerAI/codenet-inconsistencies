
// Return list with elements incremented by 1.
// >>> IncrList([1, 2, 3])
// [2, 3, 4]
// >>> IncrList([5, 3, 5, 2, 3, 3, 9, 0, 123])
// [6, 4, 6, 3, 4, 4, 10, 1, 124]
func IncrList(l []int) []int {
    n := len(l)
	for i := 0; i < n; i++ {
		l[i]++
	}
	return l
}

