"""
Evaluate performance of pre-trained Markov controller models.
"""
import os
import sys
import logging
import argparse
import json
import shutil
import numpy as np
from datetime import datetime

# Add parent directory to system path to import modules correctly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simulation import (
    Simulation, 
    ControlStrategy, 
    REAL_COMPONENTS_AVAILABLE
)

def setup_logging(output_dir):
    """Configure logging for the model evaluation."""
    os.makedirs(output_dir, exist_ok=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(os.path.join(output_dir, "evaluation.log")),
            logging.StreamHandler()
        ]
    )

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Evaluate pre-trained Markov models")
    
    parser.add_argument(
        "--model-paths", 
        type=str, 
        nargs='+',
        help="Paths to markov_model.json files to evaluate"
    )
    
    parser.add_argument(
        "--models-list-file", 
        type=str,
        help="Path to a file containing model paths (one per line), alternative to --model-paths"
    )
    
    parser.add_argument(
        "--output-dir", 
        type=str, 
        default="model_evaluation",
        help="Base directory for storing evaluation results"
    )
    
    parser.add_argument(
        "--duration", 
        type=float, 
        default=14.0,
        help="Duration of each evaluation simulation in days"
    )
    
    parser.add_argument(
        "--time-step", 
        type=int, 
        default=5,
        help="Simulation time step in minutes"
    )
    
    return parser.parse_args()

def get_model_paths(args):
    """Get list of model paths from arguments or file."""
    if args.model_paths:
        return args.model_paths
    
    if args.models_list_file and os.path.exists(args.models_list_file):
        with open(args.models_list_file, 'r') as f:
            return [line.strip() for line in f if line.strip()]
    
    return []

def convert_to_serializable(obj):
    """Convert NumPy types to standard Python types for JSON serialization."""
    if isinstance(obj, (np.intc, np.intp, np.int8, np.int16, np.int32, np.int64,
                         np.uint8, np.uint16, np.uint32, np.uint64)):
        return int(obj)
    elif isinstance(obj, (np.float16, np.float32, np.float64)):
        return float(obj)
    elif isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, (np.ndarray,)):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {k: convert_to_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_to_serializable(item) for item in obj]
    else:
        return obj

def calculate_overall_score(results, all_results_list=None):
    """Calculate overall score for a model. Lower score is better."""
    # If no results list provided, use traditional non-normalized calculation
    if all_results_list is None or not all_results_list:
        energy_consumption = results.get('energy_consumption', 0)
        co2_over_1000_pct = results.get('co2_over_1000_pct', 0)
        ventilation_on_empty_pct = results.get('ventilation_on_empty_pct', 0)
        
        return (
            0.3 * energy_consumption + 
            0.4 * co2_over_1000_pct + 
            0.3 * ventilation_on_empty_pct
        )
    
    # Extract values for current model
    current_energy = results.get('energy_consumption', float('inf'))
    current_avg_co2 = results.get('avg_co2', float('inf'))
    current_max_co2 = results.get('max_co2', float('inf'))
    current_vent_empty_pct = results.get('ventilation_on_empty_pct', float('inf'))
    current_avg_noise = results.get('avg_noise', float('inf'))
    
    # Find maximum values across all experiments for normalization
    max_energy = max([r.get('energy_consumption', 0) for r in all_results_list], default=1)
    max_avg_co2 = max([r.get('avg_co2', 0) for r in all_results_list], default=1)
    max_max_co2 = max([r.get('max_co2', 0) for r in all_results_list], default=1)
    max_vent_empty_pct = max([r.get('ventilation_on_empty_pct', 0) for r in all_results_list], default=1)
    
    noise_values = [r.get('avg_noise', 0) for r in all_results_list if r.get('avg_noise', 0) > 0]
    max_avg_noise = max(noise_values, default=1)
    min_avg_noise = min(noise_values, default=0) if noise_values else 0
    
    # Normalize values (0-1, where 0 is better)
    norm_energy = current_energy / max_energy if max_energy > 0 else 0
    norm_avg_co2 = current_avg_co2 / max_avg_co2 if max_avg_co2 > 0 else 0
    norm_vent_empty_pct = current_vent_empty_pct / 100  # Already percentage, scale to 0-1
    
    # Normalize noise (0 = best, 1 = worst)
    noise_range = max_avg_noise - min_avg_noise
    norm_avg_noise = (current_avg_noise - min_avg_noise) / noise_range if noise_range > 0 else 0
    
    # Weights for different metrics
    weight_energy = 0.40      # Energy efficiency
    weight_avg_co2 = 0.30     # Air quality
    weight_avg_noise = 0.20   # Noise level
    weight_vent_empty = 0.10  # Smart operation
    
    # Calculate final score
    score = (
        weight_energy * norm_energy +
        weight_avg_co2 * norm_avg_co2 +
        weight_avg_noise * norm_avg_noise +
        weight_vent_empty * norm_vent_empty_pct
    )
    
    return score

def main():
    """Evaluate pre-trained Markov models."""
    args = parse_arguments()
    
    # Get model paths
    model_paths = get_model_paths(args)
    
    if not model_paths:
        print("Error: No model paths provided. Use --model-paths or --models-list-file.")
        return 1
    
    # Create base output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_output_dir = os.path.join(args.output_dir, timestamp)
    setup_logging(base_output_dir)
    
    if not REAL_COMPONENTS_AVAILABLE:
        logging.error("Real components not available. Cannot evaluate Markov models.")
        return 1
    
    logging.info(f"Starting evaluation of {len(model_paths)} models")
    logging.info(f"Base output directory: {base_output_dir}")
    logging.info(f"Evaluation duration: {args.duration} days")
    
    # Create directory for the final best model
    final_models_dir = os.path.join("trained_models")
    os.makedirs(final_models_dir, exist_ok=True)
    
    # Results for all evaluations
    evaluation_results = []
    
    # Evaluate each model
    for model_idx, model_path in enumerate(model_paths, 1):
        if not os.path.exists(model_path):
            logging.error(f"Model file not found: {model_path}")
            continue
            
        logging.info(f"Evaluating model {model_idx}/{len(model_paths)}: {model_path}")
        
        # Create evaluation-specific output directory
        eval_dir = os.path.join(base_output_dir, f"eval_{model_idx}")
        os.makedirs(eval_dir, exist_ok=True)
        
        # Get directory for the latest model that will be loaded by default
        trained_models_dir = os.path.join(eval_dir, "sim_data", "markov")
        os.makedirs(trained_models_dir, exist_ok=True)
        
        # Copy model to the standard location where it will be loaded
        latest_model_path = os.path.join(trained_models_dir, "markov_model.json")
        shutil.copy2(model_path, latest_model_path)
        
        # Create simulation with evaluation settings
        sim = Simulation(
            output_dir=eval_dir, 
            time_step_minutes=args.time_step,
            use_pretrained_markov=True
        )
        
        # Set Markov parameters for evaluation mode
        sim.markov_explore_rate = 0.01
        sim.markov_learning_rate = 0.0
        
        # Set up evaluation experiment
        experiment = sim.setup_experiment(
            name=f"Markov Evaluation {model_idx}",
            strategy=ControlStrategy.MARKOV,
            duration_days=args.duration,
            description=f"Evaluating Markov model from {model_path}"
        )
        
        # Run evaluation simulation
        logging.info(f"Running evaluation simulation for model {model_idx}...")
        result = sim.run_experiment(experiment)
        
        # Check if simulation was successful
        if isinstance(result, dict) and not result.get('error'):
            # Store results with model path
            result['model_path'] = model_path
            result['model_index'] = model_idx
            evaluation_results.append(result)
            
            # Log key metrics
            logging.info(f"Model {model_idx} evaluation metrics:")
            logging.info(f"  - Energy consumption: {result['energy_consumption']:.2f} kWh")
            logging.info(f"  - Average CO2: {result['avg_co2']:.1f} ppm")
            logging.info(f"  - Time CO2 > 1000 ppm: {result['co2_over_1000_pct']:.1f}%")
            logging.info(f"  - Time ventilation on while occupied: {result['ventilation_on_occupied_pct']:.1f}%")
            logging.info(f"  - Time ventilation on while empty: {result['ventilation_on_empty_pct']:.1f}%")
        else:
            logging.error(f"Evaluation failed for model {model_idx}: {result.get('error', 'Unknown error')}")
    
    # If we have results, find the best model
    if evaluation_results:
        # Calculate overall scores
        for result in evaluation_results:
            result['overall_score'] = calculate_overall_score(result, evaluation_results)
        
        # Sort by overall score (lower is better)
        evaluation_results.sort(key=lambda x: x['overall_score'])
        
        # Get the best model
        best_model = evaluation_results[0]
        
        logging.info("\nEvaluation Summary:")
        logging.info(f"Total models evaluated: {len(evaluation_results)}")
        
        logging.info("\nBest model:")
        logging.info(f"  - Path: {best_model['model_path']}")
        logging.info(f"  - Overall score: {best_model['overall_score']:.2f}")
        logging.info(f"  - Energy consumption: {best_model['energy_consumption']:.2f} kWh")
        logging.info(f"  - Average CO2: {best_model['avg_co2']:.1f} ppm")
        logging.info(f"  - Time CO2 > 1000 ppm: {best_model['co2_over_1000_pct']:.1f}%")
        
        # Copy best model to final location
        best_overall_path = os.path.join(final_models_dir, "markov_model_best_overall.json")
        shutil.copy2(best_model['model_path'], best_overall_path)
        logging.info(f"\nBest model copied to: {best_overall_path}")
        
        # Save summary of all evaluations
        summary_path = os.path.join(base_output_dir, "evaluation_summary.json")
        with open(summary_path, 'w') as f:
            json.dump(
                convert_to_serializable({
                    "timestamp": timestamp,
                    "models_evaluated": len(evaluation_results),
                    "best_model": {
                        "path": best_model['model_path'],
                        "score": best_model['overall_score'],
                        "metrics": {
                            "energy_consumption": best_model['energy_consumption'],
                            "avg_co2": best_model['avg_co2'],
                            "co2_over_1000_pct": best_model['co2_over_1000_pct'],
                            "ventilation_on_empty_pct": best_model['ventilation_on_empty_pct']
                        }
                    },
                    "all_results": evaluation_results
                }),
                f, 
                indent=2
            )
        logging.info(f"Evaluation summary saved to: {summary_path}")
    else:
        logging.error("No successful evaluations to summarize")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())