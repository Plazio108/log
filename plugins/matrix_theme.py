import random
from engine import BaseWidget, DefaultLoginBox
from gleaf.styles import Modifiers

# ==========================================
# 1. CUSTOM ANIMATED WIDGET
# ==========================================
class MatrixRainBackground(BaseWidget):
    """An animated 'Digital Rain' background that updates independently of the UI."""
    def __init__(self, config: dict):
        # Render at z_index 0 (behind everything)
        super().__init__(name="matrix_rain", x=0, y=0, z_index=config["layout"]["z_background"])
        
        # Pull custom configuration injected by the plugin setup
        self.matrix_cfg = config["matrix_plugin"]
        self.speed = self.matrix_cfg["fall_speed"]
        self.chars = self.matrix_cfg["charset"]
        
        # State tracking for the animation
        self.accumulator = 0.0
        self.drops = []
        self.last_width = 0

    def update(self, dt: float, engine: 'GreeterEngine'):
        """Runs every frame. Uses delta-time (dt) to keep animation speed consistent."""
        self.accumulator += dt
        
        # Only advance the animation if enough time has passed
        if self.accumulator >= self.speed:
            self.accumulator = 0.0
            
            # Handle terminal resizing dynamically
            current_width = engine.canvas.width
            if current_width != self.last_width:
                # Initialize random starting heights for each column
                self.drops = [random.randint(-current_width, 0) for _ in range(current_width)]
                self.last_width = current_width

            # Make the "rain" fall
            height = engine.canvas.height
            for i in range(len(self.drops)):
                self.drops[i] += 1
                # Reset drop to top if it falls off the screen
                if self.drops[i] > height:
                    self.drops[i] = random.randint(-10, 0)

    def draw(self, canvas, config: dict):
        """Renders the matrix rain to the gleaf canvas."""
        thm = config["theme"]
        
        # First, fill the screen with absolute black
        canvas.edit_region_colors(0, 0, canvas.width, canvas.height, None, thm["bg_color"])
        
        # Draw the rain drops
        for x, y in enumerate(self.drops):
            if y >= 0 and y < canvas.height:
                char = random.choice(self.chars)
                # The leading character is bright, the rest is dim (simulated by drawing only the head)
                canvas.put_str(
                    x, y, char, 
                    thm["text_matrix_head"], thm["bg_color"], 
                    Modifiers.BOLD, None
                )
                
                # Draw a dimmer trail character right above it
                if y - 1 >= 0:
                    trail_char = random.choice(self.chars)
                    canvas.put_str(
                        x, y - 1, trail_char, 
                        thm["text_matrix_trail"], thm["bg_color"], 
                        Modifiers.DIM, None
                    )


# ==========================================
# 2. PLUGIN INJECTION POINT
# ==========================================
def setup(engine):
    """
    Called by GreeterEngine._load_plugins() before the main loop starts.
    This is where the plugin hijacks the engine state.
    """
    
    # 1. INJECT NEW CONFIGURATION
    # Overwrite the default theme colors to fit the Matrix vibe
    engine.config["theme"].update({
        "bg_color": (5, 5, 5),               # Deep black
        "box_bg": (15, 25, 15),              # Dark green-tinted box
        "text_main": (150, 255, 150),        # Pale green text
        "text_accent": (50, 255, 50),        # Bright neon green accent
        "text_matrix_head": (200, 255, 200), # Custom color for the rain head
        "text_matrix_trail": (0, 150, 0),    # Custom color for the rain trail
    })
    
    # Modify default text and layout
    engine.config["text"]["title"] = " THE MATRIX - LOGIN "
    engine.config["text"]["user_active"] = "neo> "
    engine.config["text"]["user_idle"]   = "neo> "
    engine.config["text"]["pass_active"] = "key> "
    engine.config["text"]["pass_idle"]   = "key> "
    engine.config["text"]["mask_char"]   = "#"
    engine.config["layout"]["box_width"] = 38
    
    # Add a completely new configuration block specific to this plugin
    engine.config["matrix_plugin"] = {
        "fall_speed": 0.08, # How fast the rain falls in seconds
        "charset": "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ@#$%^&*!?"
    }

    # 2. CLEAR DEFAULT WIDGETS
    # This removes the built-in DefaultBackground, leaving a blank slate.
    engine.widgets.clear()

    # 3. ASSEMBLE THE NEW SCENE
    # Add our custom animated background
    engine.add_widget(MatrixRainBackground(engine.config))
    
    # Re-add the DefaultLoginBox. 
    # Because we mutated the config dictionary BEFORE passing it, 
    # the DefaultLoginBox will automatically adopt the new Matrix colors and text!
    engine.add_widget(DefaultLoginBox(engine.config))
