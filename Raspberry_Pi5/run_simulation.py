# run_simulation.py
"""
Main script for running ventilation simulation experiments.
"""
import os
import sys
import logging
import json
import argparse
from datetime import datetime
from tqdm import tqdm

# Add the parent directory to system path to import modules correctly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simulation import (
    Simulation, 
    ControlStrategy, 
    run_complete_simulation,
    REAL_COMPONENTS_AVAILABLE
)

# Import these directly 
from simulation.occupants import OccupantBehaviorModel
from simulation.ventilation import VentilationSystem, VentilationMode, VentilationSpeed

def setup_logging(output_dir, console_level=logging.ERROR):
    """Configure logging for the simulation."""
    os.makedirs(output_dir, exist_ok=True)
    
    # Configure root logger
    logging.basicConfig(
        level=logging.INFO,  # Keep file logging detailed
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(os.path.join(output_dir, "simulation.log")),
        ]
    )
    
    # Add console handler with higher threshold to reduce output
    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    
    # Get the root logger and add our custom handler
    root_logger = logging.getLogger()
    root_logger.addHandler(console_handler)

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Run ventilation simulation experiments")
    
    parser.add_argument(
        "--output-dir", 
        type=str, 
        default="simulation_results",
        help="Directory for storing simulation output"
    )
    
    parser.add_argument(
        "--duration", 
        type=float, 
        default=7.0,
        help="Duration of each experiment in days"
    )
    
    parser.add_argument(
        "--time-step", 
        type=int, 
        default=5,
        help="Simulation time step in minutes"
    )
    
    parser.add_argument(
        "--strategies", 
        type=str, 
        nargs="+",
        choices=["all", "threshold", "constant", "scheduled", "interval", "markov", "predictive"],
        default=["all"],
        help="Control strategies to evaluate"
    )
    
    parser.add_argument(
        "--config", 
        type=str,
        help="Path to JSON configuration file"
    )
    
    parser.add_argument(
        "--use-pretrained", 
        action="store_true",
        help="Use pre-trained Markov model for evaluation"
    )
    
    parser.add_argument(
        "--training-mode", 
        action="store_true",
        help="Run in training mode with higher exploration rate"
    )
    
    parser.add_argument(
        "--compare-only",
        action="store_true",
        help="Only compare existing experiments without running new ones"
    )
    
    parser.add_argument(
        "--compare-fair",
        action="store_true",
        help="Compare strategies using identical occupant behavior for fair comparison"
    )
    
    return parser.parse_args()

def load_config(config_path):
    """Load configuration from JSON file."""
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Error loading configuration: {e}")
        return None

def main():
    """Main function to run simulation experiments."""
    args = parse_arguments()
    
    # Set up logging with higher threshold for console output
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join(args.output_dir, timestamp)
    setup_logging(output_dir, console_level=logging.ERROR)  # Only show ERROR and CRITICAL in console
    
    logging.info("Starting ventilation simulation")
    logging.info(f"Output directory: {output_dir}")
    
    # Load configuration if provided
    config = None
    if args.config:
        config = load_config(args.config)
        if config:
            logging.info(f"Loaded configuration from {args.config}")
    else:
        # Use default configuration
        default_config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 
                                          "simulation", "config.json")
        if os.path.exists(default_config_path):
            config = load_config(default_config_path)
            if config:
                logging.info(f"Loaded default configuration from {default_config_path}")
        else:
            config = {}  # Empty config if no file exists

    # If compare-only mode is active
    if args.compare_only:
        if not config or "experiment_dirs" not in config:
            logging.error("Cannot compare experiments: no experiment directories specified in config")
            return
        
        # Create simulation object
        sim = Simulation(output_dir=output_dir, time_step_minutes=args.time_step)
        
        # Load experiments from specified directories
        experiment_ids = []
        for exp_dir in config["experiment_dirs"]:
            try:
                with open(os.path.join(exp_dir, "config.json"), 'r') as f:
                    exp_config = json.load(f)
                
                with open(os.path.join(exp_dir, "results.json"), 'r') as f:
                    exp_results = json.load(f)
                
                # Add to experiments list
                exp_config["results"] = exp_results
                exp_config["output_dir"] = exp_dir
                sim.experiments.append(exp_config)
                experiment_ids.append(len(sim.experiments))
                
                logging.info(f"Loaded experiment from {exp_dir}")
            except Exception as e:
                logging.error(f"Error loading experiment from {exp_dir}: {e}")
        
        # Compare loaded experiments
        if experiment_ids:
            sim.compare_experiments(experiment_ids)
            logging.info("Comparison generated successfully")
        else:
            logging.error("No valid experiments found to compare")
        
        return
    
    # Determine strategies to evaluate
    strategies_to_run = []
    if "all" in args.strategies:
        strategies_to_run = [
            (ControlStrategy.CONSTANT, "Constant Low Ventilation"),
            (ControlStrategy.THRESHOLD, "Threshold-Based Control"),
            (ControlStrategy.SCHEDULED, "Scheduled Ventilation"),
            (ControlStrategy.INTERVAL, "Regular Interval Ventilation"),
            (ControlStrategy.MARKOV, "Markov-Based Control")
        ]
        
        if REAL_COMPONENTS_AVAILABLE:
            strategies_to_run.append((ControlStrategy.PREDICTIVE, "Occupancy Prediction"))
    else:
        strategy_mapping = {
            "constant": (ControlStrategy.CONSTANT, "Constant Low Ventilation"),
            "threshold": (ControlStrategy.THRESHOLD, "Threshold-Based Control"),
            "scheduled": (ControlStrategy.SCHEDULED, "Scheduled Ventilation"),
            "interval": (ControlStrategy.INTERVAL, "Regular Interval Ventilation"),
            "markov": (ControlStrategy.MARKOV, "Markov-Based Control"),
            "predictive": (ControlStrategy.PREDICTIVE, "Occupancy Prediction")
        }
        
        for strategy_name in args.strategies:
            if strategy_name in strategy_mapping:
                strategies_to_run.append(strategy_mapping[strategy_name])
    
    # Check if predictive strategy is requested but not available
    if not REAL_COMPONENTS_AVAILABLE and any(s[0] == ControlStrategy.PREDICTIVE for s in strategies_to_run):
        logging.warning("Predictive strategy requested but real components not available. Skipping.")
        strategies_to_run = [s for s in strategies_to_run if s[0] != ControlStrategy.PREDICTIVE]
    
    # Create and run simulation
    sim = Simulation(
        output_dir=output_dir, 
        time_step_minutes=args.time_step,
        use_pretrained_markov=args.use_pretrained
    )
    
    # Set Markov parameters based on mode
    if args.training_mode:
        sim.markov_explore_rate = 0.5  # Higher for training
        sim.markov_learning_rate = 0.3  # Higher for training
    else:
        sim.markov_explore_rate = 0.0  # Lower for evaluation
        sim.markov_learning_rate = 0.0  # Lower for evaluation

    # Patch the Simulation.run_experiment method to use tqdm
    original_run_experiment = sim.run_experiment
    
    def run_experiment_with_progress(experiment=None):
        """Patched version of run_experiment that uses tqdm for progress"""
        # Select experiment to run (same as original method)
        if experiment is None:
            if sim.current_experiment is None:
                raise ValueError("No experiment configured. Call setup_experiment first.")
            experiment = sim.current_experiment
        elif isinstance(experiment, int):
            if experiment < 1 or experiment > len(sim.experiments):
                raise ValueError(f"Invalid experiment ID: {experiment}")
            experiment = sim.experiments[experiment - 1]
        
        print(f"Running experiment: {experiment['name']} ({experiment['duration_days']} days)")
        
        # Initialize environment and other setup
        sim.environment.reset(
            initial_co2=experiment['initial_conditions']['co2'],
            initial_temp=experiment['initial_conditions']['temperature']
        )
        
        # Set experiment start date
        start_date = datetime.fromisoformat(experiment['start_time'])
        sim.environment.current_time = start_date
        sim.occupants = OccupantBehaviorModel(
            start_date=start_date,
            num_residents=2  # Fixed for this simulation
        )
        
        # Set up ventilation strategy
        sim.ventilation = VentilationSystem(
            sim.environment,
            strategy=ControlStrategy[experiment['strategy']]
        )
        
        # Set up real components if available
        sim._setup_real_components(experiment)
        
        # Clear data buffer
        sim.data_buffer = []
        
        # Run simulation with progress bar
        sim.running = True
        sim.current_step = 0
        sim.max_steps = experiment['total_steps']
        
        try:
            # Create a progress bar
            with tqdm(total=sim.max_steps, desc=f"Simulating {experiment['strategy']}", 
                      bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]') as pbar:
                
                while sim.running and sim.current_step < sim.max_steps:
                    # Update components
                    sim._simulate_step()
                    
                    # Flush data buffer periodically
                    if len(sim.data_buffer) >= sim.buffer_max_size:
                        sim._flush_data_buffer(experiment['csv_path'])
                    
                    # Update progress bar
                    pbar.update(1)
                    
                    # Check for early termination
                    if not sim.running:
                        logging.info("Experiment terminated early")
                        break
                    
                    sim.current_step += 1
            
            # Ensure all data is flushed
            sim._flush_data_buffer(experiment['csv_path'])
            
            # Calculate experiment results
            results = sim._calculate_results(experiment['csv_path'])
            experiment['results'] = results
            
            # Save results
            results_path = os.path.join(experiment['output_dir'], "results.json")
            with open(results_path, 'w') as f:
                # Handle Enum serialization in results
                json_safe_results = sim._prepare_for_json(results)
                json.dump(json_safe_results, f, indent=2)
            
            # Generate plots
            sim._generate_plots(experiment)
            
            print(f"Completed: {experiment['name']}")
            print(f"Energy consumption: {results['energy_consumption']:.2f} kWh, Avg CO2: {results['avg_co2']:.1f} ppm")
            
            return results
                
        except Exception as e:
            logging.error(f"Error during experiment: {e}", exc_info=True)
            return {"error": str(e)}
        finally:
            sim.running = False
    
    # Replace the original method with our patched version
    sim.run_experiment = run_experiment_with_progress

    # Patch the compare_strategies_with_shared_behavior method
    original_compare = sim.compare_strategies_with_shared_behavior
    
    def compare_strategies_with_progress(strategies, duration_days=7.0, output_dir=None):
        """
        Run multiple experiments with different strategies but identical occupant behavior.
        Modified to include progress bars for each experiment.
        """
        from simulation.occupants import ActivityType
        
        if output_dir:
            sim.output_dir = output_dir
            os.makedirs(output_dir, exist_ok=True)
        
        # Create shared occupant behavior for all experiments
        start_date = sim.initial_date or datetime(2023, 1, 1, 0, 0, 0)
        # Use the proper import here
        shared_occupant_model = OccupantBehaviorModel(start_date=start_date, num_residents=2)
        
        # Store original occupants model to restore later
        original_occupants = sim.occupants
        
        results = []
        experiment_ids = []
        
        print(f"Starting fair comparison of {len(strategies)} strategies using shared behavior")
        
        # Run each strategy with the same occupant behavior
        for i, strategy in enumerate(strategies):
            # Reset environment but keep the same occupant model
            sim.environment.reset()
            sim.environment.current_time = start_date
            
            # Use the shared occupant model
            sim.occupants = shared_occupant_model
            
            # Reset occupant model to initial state
            sim.occupants.current_time = start_date
            sim.occupants.current_occupants = sim.occupants.num_residents
            
            # Set initial activities
            sim.occupants.resident_activities = [ActivityType.AT_HOME] * sim.occupants.num_residents
            sim.occupants.occupancy_history = []
            sim.occupants.event_log = []
            
            # Set up the experiment
            experiment = sim.setup_experiment(
                name=f"{strategy.name} Strategy",
                strategy=strategy,
                duration_days=duration_days,
                description=f"Testing {strategy.name} strategy with shared occupant behavior"
            )
            
            # Run the experiment
            print(f"Running experiment {i+1}/{len(strategies)}: {strategy.name}")
            
            # Manually handle the experiment execution with a progress bar
            sim.environment.reset(
                initial_co2=experiment['initial_conditions']['co2'],
                initial_temp=experiment['initial_conditions']['temperature']
            )
            
            # Set up ventilation strategy
            sim.ventilation = VentilationSystem(
                sim.environment,
                strategy=strategy
            )
            
            # Set up real components if available
            sim._setup_real_components(experiment)
            
            # Clear data buffer
            sim.data_buffer = []
            
            # Run simulation with progress bar
            sim.running = True
            sim.current_step = 0
            sim.max_steps = experiment['total_steps']
            
            try:
                # Create a progress bar
                with tqdm(total=sim.max_steps, desc=f"Simulating {strategy.name}", 
                          bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]') as pbar:
                    
                    while sim.running and sim.current_step < sim.max_steps:
                        # Update components
                        sim._simulate_step()
                        
                        # Flush data buffer periodically
                        if len(sim.data_buffer) >= sim.buffer_max_size:
                            sim._flush_data_buffer(experiment['csv_path'])
                        
                        # Update progress bar
                        pbar.update(1)
                        
                        # Check for early termination
                        if not sim.running:
                            break
                        
                        sim.current_step += 1
                
                # Ensure all data is flushed
                sim._flush_data_buffer(experiment['csv_path'])
                
                # Calculate experiment results
                result = sim._calculate_results(experiment['csv_path'])
                experiment['results'] = result
                
                # Save results
                results_path = os.path.join(experiment['output_dir'], "results.json")
                with open(results_path, 'w') as f:
                    json_safe_results = sim._prepare_for_json(result)
                    json.dump(json_safe_results, f, indent=2)
                
                # Generate plots
                sim._generate_plots(experiment)
                
                print(f"Completed: {strategy.name}")
                print(f"Energy consumption: {result['energy_consumption']:.2f} kWh, Avg CO2: {result['avg_co2']:.1f} ppm")
                
            except Exception as e:
                logging.error(f"Error during experiment: {e}", exc_info=True)
                result = {"error": str(e)}
            finally:
                sim.running = False
            
            results.append(result)
            experiment_ids.append(experiment['id'])
        
        # Restore original occupants model
        sim.occupants = original_occupants
        
        # Compare all experiments
        if len(experiment_ids) > 1:
            print("Generating comparison charts...")
            sim.compare_experiments(experiment_ids)
        
        print(f"Completed {len(strategies)} experiments with shared behavior")
        return results
    
    # Replace the original method with our patched version
    sim.compare_strategies_with_shared_behavior = compare_strategies_with_progress
    
    # Run selected strategies
    if args.compare_fair and args.strategies:
        # Get strategies to compare
        strategies_to_compare = []
        strategy_mapping = {
            "constant": (ControlStrategy.CONSTANT, "Constant Low Ventilation"),
            "threshold": (ControlStrategy.THRESHOLD, "Threshold-Based Control"),
            "scheduled": (ControlStrategy.SCHEDULED, "Scheduled Ventilation"),
            "interval": (ControlStrategy.INTERVAL, "Regular Interval Ventilation"),
            "markov": (ControlStrategy.MARKOV, "Markov-Based Control"),
            "predictive": (ControlStrategy.PREDICTIVE, "Occupancy Prediction")
        }

        selected_strategy_names = args.strategies
        if "all" in args.strategies:
            selected_strategy_names = ["constant", "threshold", "scheduled", "interval", "markov"]
            if REAL_COMPONENTS_AVAILABLE:
                selected_strategy_names.append("predictive")

        for strategy_name in selected_strategy_names:
            if strategy_name in strategy_mapping:
                strategies_to_compare.append(strategy_mapping[strategy_name][0])
        
        if not REAL_COMPONENTS_AVAILABLE and ControlStrategy.PREDICTIVE in strategies_to_compare:
            logging.warning("Predictive strategy requested for fair comparison but real components not available. Skipping Predictive.")
            strategies_to_compare = [s for s in strategies_to_compare if s != ControlStrategy.PREDICTIVE]

        # Run with shared behavior
        if strategies_to_compare:
            print(f"Starting fair comparison with {len(strategies_to_compare)} strategies for {args.duration} days")
            sim.compare_strategies_with_shared_behavior(strategies_to_compare, duration_days=args.duration, output_dir=output_dir)
        else:
            logging.warning("No valid strategies selected for fair comparison.")

    else:
        # Original code for running individual experiments
        for strategy, name in strategies_to_run:
            # Get strategy-specific configuration
            strategy_config = config.get(strategy.name.lower(), {}) if config else {}
            description = f"Testing {name} strategy for {args.duration} days"
            
            if strategy == ControlStrategy.INTERVAL:
                description = "10 minutes of ventilation every 60 minutes"

            # Set up experiment
            experiment = sim.setup_experiment(
                name=name,
                strategy=strategy,
                duration_days=args.duration,
                description=description
            )
            
            # Apply configuration overrides
            if strategy_config:
                strategy_key = f"{strategy.name.lower()}_strategy"
                if strategy_key in sim.ventilation.parameters:
                    sim.ventilation.parameters[strategy_key].update(strategy_config)
                    logging.info(f"Applied custom configuration for {strategy.name}")

            if strategy != ControlStrategy.MARKOV:
                current_strategy_param_key = f"{strategy.name.lower()}_strategy"
                if current_strategy_param_key in sim.ventilation.parameters and \
                   'night_mode_enabled' in sim.ventilation.parameters[current_strategy_param_key]:
                    sim.ventilation.parameters[current_strategy_param_key]['night_mode_enabled'] = False
            
            # Run experiment
            sim.run_experiment(experiment)
    
    # Compare results if multiple experiments were run (and not in fair compare mode, as that handles its own comparison)
    if len(strategies_to_run) > 1 and not args.compare_fair:
        experiment_ids_to_compare = [exp['id'] for exp in sim.experiments if exp['name'] in [s[1] for s in strategies_to_run]]
        if experiment_ids_to_compare:
            print("Generating comparison charts...")
            sim.compare_experiments(experiment_ids_to_compare)
    
    print("Simulation completed successfully.")

if __name__ == "__main__":
    main()