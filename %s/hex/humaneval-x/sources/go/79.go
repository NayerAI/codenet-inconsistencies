import (
	"fmt"
)

// You will be given a number in decimal form and your task is to convert it to
// binary format. The function should return a string, with each character representing a binary
// number. Each character in the string will be '0' or '1'.
// 
// There will be an extra couple of characters 'db' at the beginning and at the end of the string.
// The extra characters are there to help with the format.
// 
// Examples:
// DecimalToBinary(15)   # returns "db1111db"
// DecimalToBinary(32)   # returns "db100000db"
func DecimalToBinary(decimal int) string {
    return fmt.Sprintf("db%bdb", decimal)
}

