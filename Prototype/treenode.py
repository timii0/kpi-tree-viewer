import json

class TreeNode:
    def __init__(self, value, contribution=0, score=0, tier=0, type="unknown", category="unknown"):
        self.value = value
        self._score = score
        self.tier = tier
        self.type = type
        self.category = category
        self.contribution = contribution
        self.children = []  # List to store child nodes

    @property
    def score(self):
        if not self.children:
            return self._score
        return sum(child.score for child in self.children) / len(self.children)
    

    def update_tiers(self, tier=0):
        self.tier = tier

        for child in self.children:
            child.update_tiers(tier + 1)


    def add_child(self, child_node):
        #Add a child to the node(cascade level)
        if isinstance(child_node, TreeNode):
            self.children.append(child_node)
            child_node.update_tiers(self.tier + 1)
        else:
            raise TypeError("Child must be a TreeNode instance.")

    def remove_child(self, child_node):
        #Remove a child node from the current node
        if child_node in self.children:
            self.children.remove(child_node)

    def display(self, level=0):
        #Recursively display the tree structure
        print(" " * (level * 4) + f"- {self.value, self.score}")
        for child in self.children:
            child.display(level + 1)
    
    def display_tree(self, prefix="", is_last=True):
        connector = "└── " if is_last else "├── "
        print(f"{prefix}{connector}{self.value} ({self.score})")

        new_prefix = prefix + ("    " if is_last else "│   ")

        for i, child in enumerate(self.children):
            child.display_tree(new_prefix, i == len(self.children) - 1)

     
    def to_dict(self):
        parts = self.value.split("/")

        return {
            "id": parts[-1],
            "name": parts[-1],
            "category": self.category,
            "type": self.type,
            "path": self.value,
            "tier": self.tier,
            "score": self.score,
            "contribution": self.contribution,
            "children": [child.to_dict() for child in self.children]
        }
    

   
    
    def save_tree(self, filename):
        with open(filename, "w", encoding="utf-8") as fp:
            json.dump(self.to_dict(), fp,  indent=4)
        
        print(f"Tree saved to {filename}")
