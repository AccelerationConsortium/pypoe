#!/usr/bin/env python3
"""
PyPoe Model Update Utility

This interactive script tests which Poe models are currently working and helps you
update your model configuration by commenting out non-working models.

Usage:
    python scripts/utils/update_models.py

The script will:
1. Import the actual model list from PyPoe core client
2. Separate chat models from image/video generation models
3. Test chat models with real-time progress tracking
4. Show which models are working vs failing
5. Offer to update the PyPoe client code to comment out failing models
6. Generate a recommended model list for your configuration
"""

import asyncio
import sys
import os
import time
from pathlib import Path
from typing import List, Dict, Tuple, Set
from datetime import datetime

from pypoe.core.client import PoeChatClient

class ProgressTracker:
    """Real-time progress tracking for model testing."""
    
    def __init__(self, total_models: int):
        self.total_models = total_models
        self.tested_models = 0
        self.working_models = 0
        self.failed_models = 0
        self.start_time = time.time()
        
    def update(self, model_name: str, success: bool, response_time: float, error: str = None):
        """Update progress with test result."""
        self.tested_models += 1
        if success:
            self.working_models += 1
        else:
            self.failed_models += 1
            
        # Calculate progress and timing
        progress_pct = (self.tested_models / self.total_models) * 100
        elapsed_time = time.time() - self.start_time
        estimated_total = (elapsed_time / self.tested_models) * self.total_models if self.tested_models > 0 else 0
        remaining_time = estimated_total - elapsed_time
        
        # Status indicator
        status = "" if success else ""
        
        # Progress bar
        bar_width = 30
        filled = int((progress_pct / 100) * bar_width)
        bar = "█" * filled + "░" * (bar_width - filled)
        
        # Real-time update line
        print(f"\r{status} {model_name:<25} [{bar}] {progress_pct:5.1f}% "
              f"({self.tested_models}/{self.total_models}) "
              f"{self.working_models}{self.failed_models} "
              f"⏱️{response_time:.1f}s "
              f"ETA: {remaining_time/60:.1f}m", end="", flush=True)
        
        if not success and error:
            # Print error on new line, then continue progress on next line
            print(f"\n   ↳ {error[:60]}{'...' if len(error) > 60 else ''}")
        else:
            print()  # New line for successful tests

class ModelTester:
    def __init__(self):
        self.working_models = []
        self.failed_models = []
        self.model_results = {}
        self.chat_models = []
        self.image_models = []
        self.video_models = []
        
    def categorize_models(self, all_models: List[str]) -> Tuple[List[str], List[str], List[str]]:
        """Categorize models into chat, image, and video generation models."""
        
        # Image generation model patterns
        image_patterns = {
            'DALL-E', 'FLUX', 'StableDiffusion', 'Imagen', 'Seedream'
        }
        
        # Video generation model patterns  
        video_patterns = {
            'Runway', 'Veo', 'Sora', 'Kling', 'Seedance'
        }
        
        chat_models = []
        image_models = []
        video_models = []
        
        for model in all_models:
            if any(pattern in model for pattern in image_patterns):
                image_models.append(model)
            elif any(pattern in model for pattern in video_patterns):
                video_models.append(model)
            else:
                chat_models.append(model)
                
        return chat_models, image_models, video_models
        
    async def test_model(self, client, model_name: str, tracker: ProgressTracker) -> Tuple[bool, str, float]:
        """Test a single model with a simple message and update progress."""
        start_time = time.time()
        
        try:
            response = ""
            
            # Use asyncio.wait_for with timeout
            async def get_response():
                nonlocal response
                async for chunk in client.send_message(
                    "Hello! Please respond with just 'Working' to confirm you're accessible.",
                    bot_name=model_name,
                    save_history=False
                ):
                    response += chunk
                    # Stop after getting a reasonable response (first 50 chars)
                    if len(response) > 50:
                        break
                return response
            
            # 20 second timeout for each model
            response = await asyncio.wait_for(get_response(), timeout=20)
            response_time = time.time() - start_time
            
            # Check if we got a valid response
            if response and len(response.strip()) > 5:
                tracker.update(model_name, True, response_time)
                return True, response[:100] + "..." if len(response) > 100 else response, response_time
            else:
                tracker.update(model_name, False, response_time, "Empty response")
                return False, "Empty or invalid response", response_time
                
        except asyncio.TimeoutError:
            response_time = time.time() - start_time
            tracker.update(model_name, False, response_time, "Timeout (20s)")
            return False, "Timeout after 20s", response_time
            
        except Exception as e:
            response_time = time.time() - start_time
            error_msg = str(e)
            
            # Simplify common errors
            if "Cannot access private bots" in error_msg:
                simple_error = "Private/Deprecated"
            elif "insufficient" in error_msg.lower() or "quota" in error_msg.lower():
                simple_error = "Quota/Credit issue"
            elif "Bot does not exist" in error_msg:
                simple_error = "Does not exist"
            else:
                simple_error = error_msg[:50] + "..." if len(error_msg) > 50 else error_msg
                
            tracker.update(model_name, False, response_time, simple_error)
            return False, simple_error, response_time

    async def test_chat_models(self, client) -> Dict:
        """Test only chat models with real-time progress tracking."""
        print(f"Getting model list from PyPoe core client...")
        
        # Get actual models from the client
        all_models = await client.get_available_bots()
        
        # Categorize models
        self.chat_models, self.image_models, self.video_models = self.categorize_models(all_models)
        
        print(f"Found {len(all_models)} total models:")
        print(f"   Chat models: {len(self.chat_models)}")
        print(f"   Image models: {len(self.image_models)}")
        print(f"   Video models: {len(self.video_models)}")
        print()
        print(f"Testing {len(self.chat_models)} chat models...")
        print("=" * 80)
        
        # Initialize progress tracker
        tracker = ProgressTracker(len(self.chat_models))
        
        results = {
            'timestamp': datetime.now().isoformat(),
            'total_models': len(self.chat_models),
            'successful': 0,
            'failed': 0,
            'chat_models': {},
            'image_models_found': self.image_models,
            'video_models_found': self.video_models
        }
        
        # Test each chat model
        for model_name in self.chat_models:
            success, response, response_time = await self.test_model(client, model_name, tracker)
            
            results['chat_models'][model_name] = {
                'success': success,
                'response': response,
                'response_time': response_time
            }

            if success:
                results['successful'] += 1
                self.working_models.append(model_name)
            else:
                results['failed'] += 1
                self.failed_models.append(model_name)
                
            self.model_results[model_name] = results['chat_models'][model_name]
            
            # Small delay between requests to be respectful
            await asyncio.sleep(0.5)
        
        print("\n" + "=" * 80)
        return results

    def print_summary(self, results: Dict):
        """Print a comprehensive summary of test results."""
        print("CHAT MODEL TESTING SUMMARY")
        print("=" * 80)
        
        successful = results['successful']
        failed = results['failed']
        total = results['total_models']
            
        print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Results: {successful}/{total} chat models working ({successful/total*100:.1f}%)")
        print(f"Working: {successful}")
        print(f"Failed: {failed}")
        
        if self.image_models:
            print(f"Image models found (not tested): {len(self.image_models)}")
            for model in self.image_models[:5]:  # Show first 5
                print(f"   • {model}")
            if len(self.image_models) > 5:
                print(f"   ... and {len(self.image_models) - 5} more")
        
        if self.video_models:
            print(f"Video models found (not tested): {len(self.video_models)}")
            for model in self.video_models[:5]:  # Show first 5
                print(f"   • {model}")
            if len(self.video_models) > 5:
                print(f"   ... and {len(self.video_models) - 5} more")
        
        if failed > 0:
            print(f"\nFAILED CHAT MODELS ({failed}):")
            print("-" * 50)
            for model_name in self.failed_models:
                result = self.model_results[model_name]
                print(f"  • {model_name:<30} - {result['response']}")
        
        print(f"\nWORKING CHAT MODELS ({successful}):")
        print("-" * 50)
        for model_name in self.working_models:
            result = self.model_results[model_name]
            print(f"  • {model_name:<30} - {result['response_time']:.1f}s")

    def offer_to_update_client(self):
        """Offer to update the client file with working models."""
        print(f"\nUPDATE CLIENT CODE")
        print("=" * 40)
        
        print("Would you like to update the PyPoe client to comment out non-working chat models?")
        print("This will modify src/pypoe/core/client.py to disable failed models.")
        print("Image and video models will be left as-is for future testing.")
        print()
        
        response = input("Update client file? (y/N): ").strip().lower()
        
        if response in ['y', 'yes']:
            self._update_client_file()
        else:
            print("Skipping client update.")
            print("\nYou can manually update your model list using the summary above.")

    def _update_client_file(self):
        """Actually update the client file."""
        try:
            import pypoe.core.client
            client_file = Path(pypoe.core.client.__file__)
        except ImportError:
            print("Could not import pypoe.core.client")
            return
        
        if not client_file.exists():
            print(f"Client file not found: {client_file}")
            return
        
        try:
            # Create backup
            backup_file = client_file.with_suffix('.py.backup')
            with open(client_file, 'r') as f:
                content = f.read()
            
            with open(backup_file, 'w') as f:
                f.write(content)
            
            print(f"Created backup: {backup_file}")
            
            # Update only failed chat models (leave image/video models alone)
            updated_content = self._comment_out_failed_models(content)
            
            with open(client_file, 'w') as f:
                f.write(updated_content)
            
            print(f"Updated: {client_file}")
            print(f"Commented out {len(self.failed_models)} non-working chat models")
            print(f"Kept {len(self.working_models)} working chat models active")
            print(f"Left {len(self.image_models)} image models and {len(self.video_models)} video models for future testing")
            
        except Exception as e:
            print(f"Error updating client file: {e}")

    def _comment_out_failed_models(self, content: str) -> str:
        """Comment out only failed chat models, leave image/video models alone."""
        lines = content.split('\n')
        updated_lines = []
        
        for line in lines:
            stripped = line.strip()
            # Check if this line contains a model name
            if stripped.startswith('"') and stripped.endswith('",'):
                model_name = stripped[1:-2]  # Remove quotes and comma
                
                if model_name in self.failed_models:
                    # Comment out failed chat models only
                    indent = len(line) - len(line.lstrip())
                    error_reason = self.model_results[model_name]['response']
                    updated_lines.append(f'{" " * indent}# "{model_name}",  # {error_reason}')
                else:
                    updated_lines.append(line)
            else:
                updated_lines.append(line)
        
        return '\n'.join(updated_lines)

    def print_recommendations(self):
        """Print recommendations for using the working models."""
        print(f"\nRECOMMENDATIONS")
        print("=" * 40)
        
        if self.working_models:
            print("Recommended chat models to use:")
            
            # Categorize recommendations by provider
            openai_models = [m for m in self.working_models if any(pattern in m for pattern in ['GPT', 'o1', 'o3', 'o4'])]
            anthropic_models = [m for m in self.working_models if 'Claude' in m]
            google_models = [m for m in self.working_models if 'Gemini' in m]
            deepseek_models = [m for m in self.working_models if 'DeepSeek' in m]
            
            if openai_models:
                print(f"   OpenAI: {', '.join(openai_models[:3])}")
            if anthropic_models:
                print(f"   Anthropic: {', '.join(anthropic_models[:3])}")
            if google_models:
                print(f"   Google: {', '.join(google_models[:3])}")
            if deepseek_models:
                print(f"   DeepSeek: {', '.join(deepseek_models[:2])}")
                
            print(f"\nImage generation models found but not tested: {len(self.image_models)}")
            print(f"Video generation models found but not tested: {len(self.video_models)}")
            print("\nFuture enhancement: Add image/video model testing modes")
        else:
            print("No working chat models found!")
            print("Check your POE_API_KEY and internet connection.")

async def main():
    """Main function to run the model testing utility."""
    print("PyPoe Model Update Utility v2.0")
    print("=" * 50)
    print("This tool will test chat models from your PyPoe core client configuration.")
    print("Image and video models will be identified but not tested (yet).")
    print()
    
    # Check if POE_API_KEY is set
    if not os.getenv('POE_API_KEY'):
        print("POE_API_KEY not found in environment")
        print("Please set your POE API key:")
        print("  export POE_API_KEY='your-api-key-here'")
        print("Get your key from: https://poe.com/api_key")
        return 1
    
    try:
        client = PoeChatClient(enable_history=False)
        tester = ModelTester()
        
        print("Starting chat model testing with real-time progress...")
        print()
        
        # Test chat models only
        results = await tester.test_chat_models(client)
        
        # Print summary
        tester.print_summary(results)
        
        # Print recommendations
        tester.print_recommendations()
        
        # Offer to update client
        tester.offer_to_update_client()
        
        await client.close()
        
        print(f"\nChat model testing completed!")
        print(f"Results: {len(tester.working_models)} working, {len(tester.failed_models)} failed")
        
        return 0
        
    except Exception as e:
        print(f"Error during testing: {e}")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code) 