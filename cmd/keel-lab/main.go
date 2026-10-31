// keel-lab accepts one JSON campaign and delegates actual executions to Python.
package main

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"time"

	"github.com/vTg2208/keel/internal/discovery"
)

func execute(python string) error {
	var request discovery.Request
	decoder := json.NewDecoder(io.LimitReader(os.Stdin, 8192))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&request); err != nil {
		return fmt.Errorf("invalid request: %w", err)
	}
	if err := discovery.Validate(request); err != nil {
		return err
	}
	var extra any
	if err := decoder.Decode(&extra); err != io.EOF {
		return errors.New("one JSON request required")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 75*time.Second)
	defer cancel()
	command := exec.CommandContext(ctx, python, "-m", "payops.lab.bridge")
	command.Stderr = os.Stderr
	command.WaitDelay = 2 * time.Second
	input, err := command.StdinPipe()
	if err != nil {
		return err
	}
	output, err := command.StdoutPipe()
	if err != nil {
		return err
	}
	if err := command.Start(); err != nil {
		return err
	}
	defer func() {
		input.Close()
		if command.ProcessState == nil {
			command.Process.Kill()
			command.Wait()
		}
	}()
	scanner := bufio.NewScanner(output)
	scanner.Buffer(make([]byte, 8192), 2*1024*1024)
	encoder := json.NewEncoder(input)
	oracle := func(actions []string, mutation string) (discovery.Replay, error) {
		payload := map[string]any{"protocol": 1, "actions": actions, "mutation": mutation}
		if err := encoder.Encode(payload); err != nil {
			return discovery.Replay{}, err
		}
		if !scanner.Scan() {
			if ctx.Err() != nil {
				return discovery.Replay{}, errors.New("replay deadline exceeded")
			}
			if err := scanner.Err(); err != nil {
				return discovery.Replay{}, err
			}
			return discovery.Replay{}, errors.New("replay worker closed without a response")
		}
		var reply struct {
			Protocol int               `json:"protocol"`
			Result   *discovery.Replay `json:"result"`
			Error    string            `json:"error"`
		}
		if err := json.Unmarshal(scanner.Bytes(), &reply); err != nil {
			return discovery.Replay{}, err
		}
		if reply.Protocol != 1 || reply.Error != "" || reply.Result == nil {
			return discovery.Replay{}, fmt.Errorf("invalid replay response: %s", reply.Error)
		}
		return *reply.Result, nil
	}
	report, err := discovery.Run(request, oracle)
	if err != nil {
		return err
	}
	input.Close()
	if err := command.Wait(); err != nil {
		return fmt.Errorf("replay worker failed: %w", err)
	}
	return json.NewEncoder(os.Stdout).Encode(report)
}

func main() {
	python := flag.String("python", "python", "Python executable with the Keel package installed")
	flag.Parse()
	if err := execute(*python); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
