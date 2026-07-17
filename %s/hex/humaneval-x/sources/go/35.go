
// Return maximum element in the list.
// >>> MaxElement([1, 2, 3])
// 3
// >>> MaxElement([5, 3, -5, 2, -3, 3, 9, 0, 123, 1, -10])
// 123
func MaxElement(l []int) int {
    max := l[0]
	for _, x := range l {
		if x > max {
			max = x
		}
	}
	return max
}

