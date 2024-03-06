import numpy as np
import stim
from itertools import combinations


def hypergraph_pcm(H1: np.ndarray, H2: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    r1, n1 = H1.shape
    r2, n2 = H2.shape
    HX = np.append(np.kron(H1, np.eye(n2)), np.kron(np.eye(r1), H2.T), axis=1)
    HZ = np.append(np.kron(np.eye(n1), H2), np.kron(H1.T, np.eye(r2)), axis=1)

    return HX.astype(int), HZ.astype(int)


def classical_pcm(clist: list) -> np.ndarray:
    num_bits = clist.count("B")
    H = []
    for i in range(len(clist)):
        if clist[i] == "C":
            peak_i = i + 1
            one_hot_vec = np.zeros(num_bits)
            while peak_i < len(clist) and type(clist[peak_i]) != str:
                one_hot_vec[clist[peak_i]] = 1
                peak_i += 1
            H.append(one_hot_vec)

    return np.array(H, dtype=int)


def intersecting_edges(
    adjacency_matrix: np.ndarray, positions: dict[int, tuple[float, float]]
) -> set[frozenset[tuple[float, float]]]:
    # Generate list of edges.
    edges = []
    for i in range(len(adjacency_matrix)):
        for j in range(i + 1, len(adjacency_matrix)):
            if adjacency_matrix[i, j] == 1:
                edges.append((i, j))

    # Function to check if lines intersect.
    def ccw(A, B, C):
        return (C[1] - A[1]) * (B[0] - A[0]) > (B[1] - A[1]) * (C[0] - A[0])

    def do_lines_intersect(line1, line2):
        A, B = line1
        C, D = line2
        return ccw(A, C, D) != ccw(B, C, D) and ccw(A, B, C) != ccw(A, B, D)

    # Find all sets of two edges that intersect.
    intersecting_edges = set()
    for edge1, edge2 in combinations(edges, 2):
        line1 = (positions[edge1[0]], positions[edge1[1]])
        line2 = (positions[edge2[0]], positions[edge2[1]])
        if do_lines_intersect(line1, line2):
            intersecting_edges.add(frozenset((edge1, edge2)))

    # Remove pairs where the edges share a node, because they can't intersect in a plane graph.
    non_intersecting_pairs = set()
    for pair in intersecting_edges:
        edge1, edge2 = pair
        if len(set(edge1) & set(edge2)) != 0:
            non_intersecting_pairs.add(pair)
    intersecting_edges -= non_intersecting_pairs

    return intersecting_edges


class StabilizerModel:
    def __init__(
        self,
        code: str,
        circuit: stim.Circuit = None,
        rounds: int = 3,
        noise_circuit: float | list[float] = 0.0,
        noise_data: float | list[float] = 0.0,
        noise_z_check: float | list[float] = 0.0,
        noise_x_check: float | list[float] = 0.0,
        **kwargs,
    ) -> None:
        self.circuit = stim.Circuit() if circuit is None else circuit
        self.rounds = rounds

        self.qubits = []
        self.data_qubits = []
        self.z_check_qubits = []
        self.x_check_qubits = []

        if np.issubdtype(type(noise_circuit), np.number):
            self.noise_circuit = [noise_circuit / 15 for _ in range(15)]
        else:
            assert (
                len(noise_circuit) == 15
            ), f"Stabilizer measurement noise takes 15 parameters, given {len(noise_circuit)}."
            self.noise_circuit = noise_circuit

        if np.issubdtype(type(noise_data), np.number):
            self.noise_data = [noise_data / 3 for _ in range(3)]
        else:
            assert (
                len(noise_data) == 3
            ), f"Data qubit noise takes 3 parameters, given {len(noise_data)}."
            self.noise_data = noise_data

        if np.issubdtype(type(noise_z_check), np.number):
            self.noise_z_check = [noise_z_check / 3 for _ in range(3)]
        else:
            assert (
                len(noise_z_check) == 3
            ), f"Z check qubit noise takes 3 parameters, given {len(noise_z_check)}."
            self.noise_z_check = noise_z_check

        if np.issubdtype(type(noise_x_check), np.number):
            self.noise_x_check = [noise_x_check / 3 for _ in range(3)]
        else:
            assert (
                len(noise_x_check) == 3
            ), f"Data qubit noise takes 3 parameters, given {len(noise_z_check)}."
            self.noise_x_check = noise_x_check

        self.code_params: dict = kwargs
        main_code, subcode = code.split(":") if ":" in code else (code, None)
        match main_code:
            case "repetition_code":
                distance = self.code_params["distance"]
                self.qubits = np.arange(2 * distance + 1)
                self.data_qubits = self.qubits[::2]
                self.z_check_qubits = self.qubits[1::2]
                self._repetition_code()
            case "surface_code":
                scale = self.code_params["scale"]
                assert (
                    scale[0] % 2 != 0 and scale[1] % 2 != 0
                ), "Scale of the surface code must be odd."

                self.qubits = np.arange(scale[0] * scale[1])
                self.data_qubits = []
                self.x_check_qubits = []
                self.z_check_qubits = []
                for row in range(scale[0]):
                    for col in range(scale[1]):
                        curr_qubit = row * scale[1] + col
                        self.circuit.append("QUBIT_COORDS", [curr_qubit], [row, col])
                        if row % 2 == 0:
                            if col % 2 == 0:
                                self.data_qubits.append(curr_qubit)
                            else:
                                self.z_check_qubits.append(curr_qubit)
                        elif row % 2 != 0:
                            if col % 2 != 0:
                                self.data_qubits.append(curr_qubit)
                            else:
                                self.x_check_qubits.append(curr_qubit)
                self._surface_code(subcode)
            case "hypergraph_product_code":
                """TODO:
                z_pairings: {(i, j) : list[tuple]} instead of hard-coding qubit positions; for sparse codes like the HP code.
                """
                clist1 = self.code_params["clist1"]
                clist2 = self.code_params["clist2"]
                H1 = classical_pcm(clist1)
                H2 = classical_pcm(clist2)

                num_qubits = sum(H1.shape) * sum(H2.shape)
                self.qubits = np.arange(num_qubits)

                z_check_order = [
                    "Q" if s == "B" else "Z"
                    for s in clist2
                    if not np.issubdtype(type(s), np.number)
                ]

                x_check_order = [
                    "X" if s == "B" else "Q"
                    for s in clist2
                    if not np.issubdtype(type(s), np.number)
                ]

                check_order = np.array(
                    [
                        z_check_order if s == "B" else x_check_order
                        for s in clist1
                        if not np.issubdtype(type(s), np.number)
                    ]
                ).flatten()

                self.data_qubits = [q for q, s in zip(self.qubits, check_order) if s == "Q"]
                self.z_check_qubits = [q for q, s in zip(self.qubits, check_order) if s == "Z"]
                self.x_check_qubits = [q for q, s in zip(self.qubits, check_order) if s == "X"]

                self._hypergraph_product_code()
            case _:
                raise ValueError("Code not recognized.")

        # TODO: Implement X and Z error propagation analysis

    # ------------------------------------ Setters and Getters ------------------------------------

    def reset_data_qubits(self) -> None:
        # TODO: Change to `set_data_qubits` and have it set the data qubits generally.
        self.circuit.append("R", self.data_qubits)

    # -------------------------------------- Utility Methods --------------------------------------

    def display_samples(self, shots: int = 1) -> None:
        samples = self.circuit.compile_sampler().sample(shots)
        for i, sample in enumerate(samples):
            round_list = []
            for j, outcome in enumerate(sample):
                round_list.append("o" if outcome else "_")

                # Line formatting.
                if ((j + 1) % len(self.z_check_qubits) == 0) and ((j + 1) != len(sample) - 1):
                    round_list[j] += "\n"
                if (j + 1) == (1 + self.rounds) * len(self.z_check_qubits):
                    round_list[j] += "\n"
            print(f"Shot {i + 1}:\n" + "".join(round_list))
        print()

    def display_detector_samples(self, shots: int = 1) -> None:
        samples = self.circuit.compile_detector_sampler().sample(shots, append_observables=True)
        for i, sample in enumerate(samples):
            round_list = []
            for j, outcome in enumerate(sample):
                round_list.append("x" if outcome else "_")

                # Line formatting.
                if (j + 1) % len(self.z_check_qubits) == 0:
                    round_list[j] += "\n"
                if (j + 1) == self.rounds * len(self.z_check_qubits):
                    round_list[j] += "\n"
            print(f"Shot {i + 1}:\n" + "".join(round_list))
        print()

    def shot(self, detector: bool = True) -> None:
        # TODO: Update.
        sample = (
            self.circuit.compile_detector_sampler() if detector else self.circuit.compile_sampler()
        ).sample(1)[0]

        # Account for dummy measurement when using detectors.
        effective_rounds = self.rounds if detector else self.rounds + 1

        marker = "x" if detector else "o"
        round_list = [marker if outcome else "_" for outcome in sample]
        return np.reshape(round_list, (effective_rounds, len(sample) // effective_rounds))

    def print(self) -> None:
        print(self.circuit, "\n")

    # ------------------------------------------- Codes -------------------------------------------

    def _hypergraph_product_code(self) -> None:
        qubit_pos = self.code_params["pos"]
        
        clist1 = self.code_params["clist1"]
        clist2 = self.code_params["clist2"]
        H1 = classical_pcm(clist1)
        H2 = classical_pcm(clist2)
        HX, HZ = hypergraph_pcm(H1, H2)
        print(HZ)
        print()
        print(HX)

    def _surface_code(self, subcode: str) -> None:
        scale = self.code_params["scale"]

        self.circuit.append("R", self.qubits)

        # TODO: See to remove this.
        self.circuit.append("M", self.z_check_qubits + self.x_check_qubits)

        # Check and noise.
        circuit = stim.Circuit()
        for row in range(scale[0]):
            for col in range(scale[1]):
                curr_qubit = row * scale[1] + col
                if row % 2 == 0 and col % 2 != 0:
                    # Z check and boundary conditions.
                    circuit.append("CNOT", [curr_qubit - 1, curr_qubit])
                    circuit.append("CNOT", [curr_qubit + 1, curr_qubit])

                    if row == 0:
                        circuit.append("CNOT", [curr_qubit + scale[1], curr_qubit])
                    elif row == scale[0] - 1:
                        circuit.append("CNOT", [curr_qubit - scale[1], curr_qubit])
                    else:
                        circuit.append("CNOT", [curr_qubit - scale[1], curr_qubit])
                        circuit.append("CNOT", [curr_qubit + scale[1], curr_qubit])

                    # Gate noise.
                    if self.noise_circuit is not None:
                        circuit.append(
                            "PAULI_CHANNEL_2", [curr_qubit - 1, curr_qubit], self.noise_circuit
                        )
                        circuit.append(
                            "PAULI_CHANNEL_2", [curr_qubit + 1, curr_qubit], self.noise_circuit
                        )
                        if row == 0:
                            circuit.append(
                                "PAULI_CHANNEL_2",
                                [curr_qubit + scale[1], curr_qubit],
                                self.noise_circuit,
                            )
                        elif row == scale[0] - 1:
                            circuit.append(
                                "PAULI_CHANNEL_2",
                                [curr_qubit - scale[1], curr_qubit],
                                self.noise_circuit,
                            )
                        else:
                            circuit.append(
                                "PAULI_CHANNEL_2",
                                [curr_qubit - scale[1], curr_qubit],
                                self.noise_circuit,
                            )
                            circuit.append(
                                "PAULI_CHANNEL_2",
                                [curr_qubit + scale[1], curr_qubit],
                                self.noise_circuit,
                            )

                elif row % 2 != 0 and col % 2 == 0:
                    # X check and boundary conditions.
                    circuit.append("H", [curr_qubit])

                    circuit.append("CNOT", [curr_qubit - scale[1], curr_qubit])
                    circuit.append("CNOT", [curr_qubit + scale[1], curr_qubit])
                    if col == 0:
                        circuit.append("CNOT", [curr_qubit + 1, curr_qubit])
                    elif col == scale[1] - 1:
                        circuit.append("CNOT", [curr_qubit - 1, curr_qubit])
                    else:
                        circuit.append("CNOT", [curr_qubit - 1, curr_qubit])
                        circuit.append("CNOT", [curr_qubit + 1, curr_qubit])

                    circuit.append("H", [curr_qubit])
                    # TODO: Apply noise after Hadamard gates.

                    # Gate noise.
                    if self.noise_circuit is not None:
                        circuit.append(
                            "PAULI_CHANNEL_2",
                            [curr_qubit - scale[1], curr_qubit],
                            self.noise_circuit,
                        )
                        circuit.append(
                            "PAULI_CHANNEL_2",
                            [curr_qubit + scale[1], curr_qubit],
                            self.noise_circuit,
                        )
                        if col == 0:
                            circuit.append(
                                "PAULI_CHANNEL_2", [curr_qubit + 1, curr_qubit], self.noise_circuit
                            )
                        elif col == scale[1] - 1:
                            circuit.append(
                                "PAULI_CHANNEL_2", [curr_qubit - 1, curr_qubit], self.noise_circuit
                            )
                        else:
                            circuit.append(
                                "PAULI_CHANNEL_2", [curr_qubit - 1, curr_qubit], self.noise_circuit
                            )
                            circuit.append(
                                "PAULI_CHANNEL_2", [curr_qubit + 1, curr_qubit], self.noise_circuit
                            )

        # Qubit noise.
        if self.noise_data is not None:
            circuit.append("PAULI_CHANNEL_1", self.data_qubits, self.noise_data)
        if self.noise_z_check is not None:
            circuit.append("PAULI_CHANNEL_1", self.z_check_qubits, self.noise_z_check)
        if self.noise_x_check is not None:
            circuit.append("PAULI_CHANNEL_1", self.x_check_qubits, self.noise_x_check)

        # Detect changes.
        circuit.append("MR", self.z_check_qubits)
        if subcode == "z_memory":
            for k in range(len(self.z_check_qubits)):
                circuit.append(
                    "DETECTOR",
                    [
                        stim.target_rec(-1 - k),
                        stim.target_rec(-1 - k - len(self.x_check_qubits + self.z_check_qubits)),
                    ],
                )
            circuit.append("MR", self.x_check_qubits)
        elif subcode == "x_memory":
            circuit.append("MR", self.x_check_qubits)
            for k in range(len(self.x_check_qubits)):
                circuit.append(
                    "DETECTOR",
                    [
                        stim.target_rec(-1 - k),
                        stim.target_rec(-1 - k - len(self.x_check_qubits + self.z_check_qubits)),
                    ],
                )

        self.circuit += circuit * self.rounds

        self.circuit.append("M", self.data_qubits)
        num_data_qubits_z = scale[1] // 2 + 1
        num_data_qubits_x = scale[1] // 2
        row = 0
        skip = 0
        if subcode == "z_memory":
            for k in range(len(self.z_check_qubits)):
                if k % num_data_qubits_x == 0 and k != 0:
                    row += 2
                    skip += num_data_qubits_z
                lookback_records = [
                    stim.target_rec(-1 - k - len(self.data_qubits + self.x_check_qubits)),
                    stim.target_rec(-1 - k - skip),
                    stim.target_rec(-2 - k - skip),
                ]
                if row == 0:
                    lookback_records.append(stim.target_rec(-2 - k - skip - num_data_qubits_x))
                elif row == scale[0] - 1:
                    lookback_records.append(stim.target_rec(-1 - k - skip + num_data_qubits_x))
                else:
                    lookback_records.append(stim.target_rec(-1 - k - skip + num_data_qubits_x))
                    lookback_records.append(stim.target_rec(-2 - k - skip - num_data_qubits_x))
                self.circuit.append("DETECTOR", lookback_records)
        elif subcode == "x_memory":
            for k in range(len(self.x_check_qubits)):
                lookback_records = []
                if k % num_data_qubits_z == 0:
                    if k != 0:
                        skip += num_data_qubits_x
                    lookback_records.append(stim.target_rec(-2 - k - skip - num_data_qubits_x))
                elif k % num_data_qubits_z == num_data_qubits_z - 1:
                    lookback_records.append(stim.target_rec(-1 - k - skip - num_data_qubits_x))
                else:
                    lookback_records.append(stim.target_rec(-2 - k - skip - num_data_qubits_x))
                    lookback_records.append(stim.target_rec(-1 - k - skip - num_data_qubits_x))

                lookback_records += [
                    stim.target_rec(-1 - k - len(self.data_qubits + self.x_check_qubits)),
                    stim.target_rec(-1 - k - skip),
                    stim.target_rec(-2 - k - skip),
                ]
                self.circuit.append("DETECTOR", lookback_records)

        observable_lookback_indices = []
        if subcode == "z_memory":
            for k in range(scale[0] // 2 + 1):
                observable_lookback_indices.append(
                    stim.target_rec(
                        -k * (num_data_qubits_z + num_data_qubits_x) - num_data_qubits_z
                    )
                )
        elif subcode == "x_memory":
            observable_lookback_indices = [
                stim.target_rec(-1 - k) for k in range(num_data_qubits_z)
            ]

        self.circuit.append("OBSERVABLE_INCLUDE", observable_lookback_indices, 0)

    def _repetition_code(self) -> None:
        distance = self.code_params["distance"]

        # We have to add initial dummy measurements for the detector to detect change in the first
        # set of qubit measurements.
        self.circuit.append("M", self.z_check_qubits)

        circuit = stim.Circuit()

        # Stabilizer measurements.
        for m in self.z_check_qubits:
            circuit.append("CNOT", [m - 1, m])
            circuit.append("CNOT", [m + 1, m])
            if self.noise_circuit is not None:
                circuit.append("PAULI_CHANNEL_2", [m - 1, m], self.noise_circuit)
                circuit.append("PAULI_CHANNEL_2", [m + 1, m], self.noise_circuit)

        # Apply random errors on qubits.
        if self.noise_data is not None:
            circuit.append("PAULI_CHANNEL_1", self.data_qubits, self.noise_data)
        if self.noise_z_check is not None:
            circuit.append("PAULI_CHANNEL_1", self.z_check_qubits, self.noise_z_check)

        # This measures and resets (to zero) the check qubits.
        circuit.append("MR", self.z_check_qubits)

        # Compare the last measurement result to the one previous to that of the same qubit.
        for k in range(len(self.z_check_qubits)):
            circuit.append(
                "DETECTOR", [stim.target_rec(-1 - k), stim.target_rec(-1 - k - distance)]
            )

        # Concatenate the circuits.
        self.circuit += circuit * self.rounds

        # Measure data qubits at the end.
        self.circuit.append("M", self.data_qubits)
        for k in range(len(self.z_check_qubits)):
            self.circuit.append(
                "DETECTOR",
                [
                    stim.target_rec(-1 - k),
                    stim.target_rec(-2 - k),
                    stim.target_rec(-2 - k - distance),
                ],
            )

        # Add observable.
        self.circuit.append("OBSERVABLE_INCLUDE", [stim.target_rec(-1)], 0)
