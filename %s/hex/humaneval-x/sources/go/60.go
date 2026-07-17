
// SumToN is a function that sums numbers from 1 to n.
// >>> SumToN(30)
// 465
// >>> SumToN(100)
// 5050
// >>> SumToN(5)
// 15
// >>> SumToN(10)
// 55
// >>> SumToN(1)
// 1
func SumToN(n int) int {
    if n <= 0 {
		return 0
	} else {
		return n + SumToN(n - 1)
	}
}

